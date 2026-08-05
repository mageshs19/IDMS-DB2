import re


class FieldRewriter:
    """
    Rewrites legacy IDMS COBOL field references in PROCEDURE DIVISION to DB2
    host variables.

    Handles cases where Phase 2 metadata field_map is incomplete because
    Schema Listing conversion changed physical DB2 names.

    Examples:
    - DEPT-ID-0410 -> HV-DEPARTMENT-DEPT-ID-479MENT
    - DEPT-NAME-0410 -> HV-DEPARTMENT-DEPT-NAME-479MENT
    - EMP-ID-0415 -> HV-EMPLOYEE-EMP-ID-479OYEE
    - EMP-LAST-NAME-0415 -> HV-EMPLOYEE-EMP-LASTNAME-479OYEE
    - START-YEAR-0415 -> HV-EMPLOYEE-DA-STARTDATE-479OYEE(3:2)
    - OFFICE-ZIP-FIRST-FIVE-0450 -> HV-OFFICE-OFFICE-ZIPFIRSTFIVE-479FICE

    Safety:
    - Does not rewrite DATA DIVISION.
    - Does not rewrite EXEC SQL blocks.
    - Does not rewrite comments.
    - Does not rewrite existing HV-* or NI-* variables.
    - Does not rewrite quoted literals.
    - Does not rewrite standalone paragraph headers or IDMS command lines.
    """

    PROCEDURE_DIVISION = re.compile(
        r"^\s*PROCEDURE\s+DIVISION\.",
        re.IGNORECASE | re.MULTILINE,
    )

    EXEC_SQL_START = re.compile(
        r"^\s*EXEC\s+SQL\b",
        re.IGNORECASE,
    )

    EXEC_SQL_END = re.compile(
        r"^\s*END-EXEC\.?\s*$",
        re.IGNORECASE,
    )

    COMMENT_LINE = re.compile(
        r"^\s*\*",
    )

    COBOL_IDENTIFIER = re.compile(
        r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*\b",
        re.IGNORECASE,
    )

    STANDALONE_DOTTED_LINE = re.compile(
        r"^\s*[A-Z0-9-]+\.\s*$",
        re.IGNORECASE,
    )

    RESERVED_WORDS = {
        "ACCEPT",
        "ADD",
        "AFTER",
        "ALL",
        "AND",
        "ARE",
        "AREA",
        "AT",
        "BEFORE",
        "BIND",
        "BY",
        "CALL",
        "CLOSE",
        "COMMIT",
        "CONNECT",
        "CONTINUE",
        "DATA",
        "DELETE",
        "DISCONNECT",
        "DISPLAY",
        "DIVISION",
        "ELSE",
        "END",
        "END-EXEC",
        "END-IF",
        "END-PERFORM",
        "ENVIRONMENT",
        "ERASE",
        "EVALUATE",
        "EXEC",
        "EXIT",
        "FETCH",
        "FILE",
        "FIND",
        "FINISH",
        "FROM",
        "GET",
        "GOBACK",
        "IDENTIFICATION",
        "IF",
        "IN",
        "INCLUDE",
        "INTO",
        "IS",
        "KEEP",
        "MODIFY",
        "MOVE",
        "NEXT",
        "NOT",
        "OBTAIN",
        "OF",
        "OPEN",
        "OR",
        "ORDER",
        "PERFORM",
        "PROCEDURE",
        "READ",
        "READY",
        "RECORD",
        "SECTION",
        "SELECT",
        "SET",
        "SQL",
        "SQLCA",
        "SQLCODE",
        "SPACES",
        "STOP",
        "STORE",
        "THEN",
        "THRU",
        "TO",
        "UNTIL",
        "UPDATE",
        "VALUE",
        "WHEN",
        "WHERE",
        "WRITE",
    }

    DATE_PARTS = {
        "YEAR": {
            "substring_start": 3,
            "substring_length": 2,
        },
        "MONTH": {
            "substring_start": 6,
            "substring_length": 2,
        },
        "DAY": {
            "substring_start": 9,
            "substring_length": 2,
        },
    }

    def __init__(
        self,
        schema,
    ) -> None:
        self.schema = schema

        self.field_map = getattr(
            schema,
            "field_map",
            {},
        ) or {}

        self.date_part_map = getattr(
            schema,
            "date_part_map",
            {},
        ) or {}

        self.calc_key_map = getattr(
            schema,
            "calc_key_map",
            {},
        ) or {}

        self.records = getattr(
            schema,
            "records",
            {},
        ) or {}

        self.record_table_map = getattr(
            schema,
            "record_table_map",
            {},
        ) or {}

        self.suffix_record_map = self._build_suffix_record_map()
        self.host_candidates = self._build_host_candidates()
        self.rewrite_map = self._build_rewrite_map()

    def rewrite(
        self,
        text: str,
    ) -> str:
        if not text:
            return text

        match = self.PROCEDURE_DIVISION.search(text)

        if not match:
            return text

        before_procedure = text[: match.start()]
        procedure_text = text[match.start() :]

        return before_procedure + self._rewrite_procedure_text(
            procedure_text,
        )

    def _rewrite_procedure_text(
        self,
        text: str,
    ) -> str:
        result_lines = []
        in_exec_sql = False

        for line in text.splitlines():
            if self.EXEC_SQL_START.match(line):
                in_exec_sql = True
                result_lines.append(line)
                continue

            if in_exec_sql:
                result_lines.append(line)

                if self.EXEC_SQL_END.match(line):
                    in_exec_sql = False

                continue

            if self.COMMENT_LINE.match(line):
                result_lines.append(line)
                continue

            result_lines.append(
                self._rewrite_line(line),
            )

        return "\n".join(result_lines)

    def _rewrite_line(
        self,
        line: str,
    ) -> str:
        if not line.strip():
            return line

        if self.STANDALONE_DOTTED_LINE.match(line):
            return line

        protected_ranges = self._protected_ranges(line)

        def replace_token(match):
            token = match.group(0)

            if self._is_protected(
                start=match.start(),
                end=match.end(),
                ranges=protected_ranges,
            ):
                return token

            replacement = self._replacement_for_token(token)

            if not replacement:
                return token

            return replacement

        return self.COBOL_IDENTIFIER.sub(
            replace_token,
            line,
        )

    def _replacement_for_token(
        self,
        token: str,
    ):
        normalized = self._normalize_cobol_name(token)

        if not normalized:
            return None

        if normalized in self.RESERVED_WORDS:
            return None

        if normalized.startswith("HV-"):
            return None

        if normalized.startswith("NI-"):
            return None

        direct = self.rewrite_map.get(normalized)

        if direct:
            return direct

        underscore_key = normalized.replace("-", "_")

        direct = self.rewrite_map.get(underscore_key)

        if direct:
            return direct

        suffix_removed = self._remove_numeric_suffix(normalized)

        if suffix_removed and suffix_removed != normalized:
            direct = self.rewrite_map.get(suffix_removed)

            if direct:
                return direct

            direct = self.rewrite_map.get(
                suffix_removed.replace("-", "_"),
            )

            if direct:
                return direct

            compact = self._compact_name(suffix_removed)

            direct = self.rewrite_map.get(compact)

            if direct:
                return direct

        inferred = self._infer_replacement_from_schema(
            token=normalized,
        )

        if inferred:
            self._add_rewrite_aliases(
                rewrite_map=self.rewrite_map,
                key=normalized,
                value=inferred,
                overwrite=True,
            )

            return inferred

        return None

    def _build_rewrite_map(
        self,
    ):
        rewrite_map = {}

        self._merge_field_map(
            rewrite_map,
        )

        self._merge_date_part_map(
            rewrite_map,
        )

        self._merge_calc_key_map(
            rewrite_map,
        )

        self._merge_schema_fallback_map(
            rewrite_map,
        )

        return rewrite_map

    def _merge_field_map(
        self,
        rewrite_map,
    ) -> None:
        for legacy_field, metadata in self.field_map.items():
            if not isinstance(metadata, dict):
                continue

            host = metadata.get("host")

            if not host:
                continue

            value = self._normalize_host_name(
                str(host),
            )

            if not value:
                continue

            keys = [
                str(legacy_field),
                metadata.get("legacy_field"),
                metadata.get("column"),
            ]

            for key_value in keys:
                if not key_value:
                    continue

                self._add_rewrite_aliases(
                    rewrite_map=rewrite_map,
                    key=str(key_value),
                    value=value,
                    overwrite=False,
                )

    def _merge_date_part_map(
        self,
        rewrite_map,
    ) -> None:
        for legacy_field, metadata in self.date_part_map.items():
            if not isinstance(metadata, dict):
                continue

            host = metadata.get("host")

            if not host:
                continue

            host_name = self._normalize_host_name(
                str(host),
            )

            if not host_name:
                continue

            substring_start = metadata.get("substring_start")
            substring_length = metadata.get("substring_length")

            if substring_start and substring_length:
                value = f"{host_name}({substring_start}:{substring_length})"
            else:
                value = host_name

            self._add_rewrite_aliases(
                rewrite_map=rewrite_map,
                key=str(legacy_field),
                value=value,
                overwrite=True,
            )

    def _merge_calc_key_map(
        self,
        rewrite_map,
    ) -> None:
        for record_name, metadata in self.calc_key_map.items():
            if not isinstance(metadata, dict):
                continue

            host = metadata.get("host")
            key = (
                metadata.get("key")
                or metadata.get("primary_key")
                or metadata.get("column")
            )

            if not key:
                continue

            value = None

            if host:
                value = self._normalize_host_name(
                    str(host),
                )

            if value:
                self._add_rewrite_aliases(
                    rewrite_map=rewrite_map,
                    key=str(key),
                    value=value,
                    overwrite=True,
                )

            suffix = self._extract_numeric_suffix(str(key))

            if suffix:
                record = self._normalize_db2_name(str(record_name))

                if record:
                    self.suffix_record_map[suffix] = record

    def _merge_schema_fallback_map(
        self,
        rewrite_map,
    ) -> None:
        for candidate in self.host_candidates:
            record_name = candidate["record"]
            column_name = candidate["column"]
            host = candidate["host"]

            column_base = self._remove_generated_suffix(
                self._normalize_cobol_name(column_name),
            )

            if not column_base:
                continue

            self._add_rewrite_aliases(
                rewrite_map=rewrite_map,
                key=column_base,
                value=host,
                overwrite=False,
            )

            compact_base = self._compact_name(column_base)

            if compact_base:
                rewrite_map.setdefault(
                    compact_base,
                    host,
                )

            record_suffix = self._suffix_for_record(record_name)

            if record_suffix:
                self._add_rewrite_aliases(
                    rewrite_map=rewrite_map,
                    key=f"{column_base}-{record_suffix}",
                    value=host,
                    overwrite=True,
                )

    def _infer_replacement_from_schema(
        self,
        token: str,
    ):
        parsed = self._parse_legacy_token(
            token,
        )

        base = parsed["base"]
        suffix = parsed["suffix"]

        if not base:
            return None

        date_replacement = self._infer_date_part_replacement(
            base=base,
            suffix=suffix,
        )

        if date_replacement:
            return date_replacement

        candidates = self._candidate_hosts_for_base(
            base=base,
            suffix=suffix,
        )

        if not candidates:
            return None

        if len(candidates) == 1:
            selected = candidates[0]
        else:
            selected = self._choose_best_candidate(
                base=base,
                suffix=suffix,
                candidates=candidates,
            )

        if not selected:
            return None

        if suffix:
            self.suffix_record_map[suffix] = selected["record"]

        return selected["host"]

    def _infer_date_part_replacement(
        self,
        base: str,
        suffix,
    ):
        tokens = [
            token
            for token in base.replace("_", "-").split("-")
            if token
        ]

        if len(tokens) < 2:
            return None

        part = None
        part_index = None

        for index, token in enumerate(tokens):
            resolved_part = self._date_part_type(
                token=token,
                tokens=tokens,
            )

            if resolved_part:
                part = resolved_part
                part_index = index
                break

        if not part or part_index is None:
            return None

        base_tokens = tokens[:part_index] + tokens[part_index + 1 :]
        date_tokens = tokens.copy()
        date_tokens[part_index] = "DATE"

        joined_base = "-".join(base_tokens)
        compact_base = self._compact_name(joined_base)

        candidate_bases = self._unique_values(
            [
                "-".join(date_tokens),
                joined_base,
                "DA-" + compact_base + "DATE",
                "DA-" + joined_base + "DATE",
                compact_base + "DATE",
            ]
        )

        candidates = []

        for candidate_base in candidate_bases:
            candidates.extend(
                self._candidate_hosts_for_base(
                    base=candidate_base,
                    suffix=suffix,
                    date_only=True,
                )
            )

        if not candidates:
            return None

        if len(candidates) == 1:
            selected = candidates[0]
        else:
            selected = self._choose_best_candidate(
                base=joined_base,
                suffix=suffix,
                candidates=candidates,
            )

        if not selected:
            return None

        if suffix:
            self.suffix_record_map[suffix] = selected["record"]

        meta = self.DATE_PARTS[part]

        return (
            f"{selected['host']}("
            f"{meta['substring_start']}:{meta['substring_length']})"
        )

    def _candidate_hosts_for_base(
        self,
        base: str,
        suffix,
        date_only: bool = False,
    ):
        base_normalized = self._normalize_cobol_name(base)
        base_compact = self._compact_name(base_normalized)

        result = []
        suffix_record = self.suffix_record_map.get(suffix or "")

        for candidate in self.host_candidates:
            record_name = candidate["record"]
            column_base = candidate["base"]
            column_compact = candidate["compact"]
            datatype = candidate.get("datatype", "")

            if date_only and datatype != "DATE":
                continue

            if suffix_record and record_name != suffix_record:
                continue

            if column_base == base_normalized:
                result.append(candidate)
                continue

            if column_compact == base_compact:
                result.append(candidate)
                continue

            if base_compact and column_compact.endswith(base_compact):
                result.append(candidate)
                continue

            if base_compact and base_compact in column_compact:
                result.append(candidate)
                continue

        return self._dedupe_candidates(result)

    def _choose_best_candidate(
        self,
        base: str,
        suffix,
        candidates,
    ):
        if not candidates:
            return None

        suffix_record = self.suffix_record_map.get(suffix or "")

        if suffix_record:
            filtered = [
                candidate
                for candidate in candidates
                if candidate["record"] == suffix_record
            ]

            if len(filtered) == 1:
                return filtered[0]

            if filtered:
                candidates = filtered

        base_tokens = [
            token
            for token in base.replace("_", "-").split("-")
            if token
        ]

        first_token = base_tokens[0] if base_tokens else ""
        base_compact = self._compact_name(base)

        scored = []

        for candidate in candidates:
            score = 0

            record_name = candidate["record"]
            record_prefix = candidate.get("record_prefix", "")
            column_base = candidate["base"]
            column_compact = candidate["compact"]

            if base_compact == column_compact:
                score += 100

            if first_token and first_token == record_prefix:
                score += 40

            if first_token and column_base.startswith(first_token + "-"):
                score += 20

            if first_token and record_name.startswith(first_token):
                score += 10

            if base_compact and column_compact.endswith(base_compact):
                score += 5

            scored.append((score, candidate))

        scored.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        if not scored:
            return None

        top_score = scored[0][0]

        top = [
            candidate
            for score, candidate in scored
            if score == top_score
        ]

        if len(top) == 1:
            return top[0]

        return None

    def _build_suffix_record_map(
        self,
    ):
        result = {}

        for key, metadata in self.field_map.items():
            if not isinstance(metadata, dict):
                continue

            suffix = self._extract_numeric_suffix(str(key))

            if not suffix:
                legacy = metadata.get("legacy_field")

                if legacy:
                    suffix = self._extract_numeric_suffix(str(legacy))

            record = metadata.get("record") or metadata.get("table")

            if suffix and record:
                result[suffix] = self._normalize_db2_name(str(record))

        for key, metadata in self.date_part_map.items():
            if not isinstance(metadata, dict):
                continue

            suffix = self._extract_numeric_suffix(str(key))
            record = metadata.get("record") or metadata.get("table")

            if suffix and record:
                result[suffix] = self._normalize_db2_name(str(record))

        for record_name, metadata in self.calc_key_map.items():
            if not isinstance(metadata, dict):
                continue

            key = (
                metadata.get("key")
                or metadata.get("primary_key")
                or metadata.get("column")
            )

            suffix = self._extract_numeric_suffix(str(key or ""))

            if suffix:
                result[suffix] = self._normalize_db2_name(str(record_name))

        return result

    def _build_host_candidates(
        self,
    ):
        candidates = []

        for logical_record_name, physical_record_name in self._logical_physical_records():
            record = self.records.get(physical_record_name)

            if not record:
                continue

            record_prefix = self._dominant_record_prefix(record)

            for column_name, column in getattr(record, "fields", {}).items():
                column_text = self._normalize_cobol_name(str(column_name))
                base = self._remove_generated_suffix(column_text)

                host = self._host_variable(
                    record_name=logical_record_name,
                    column_name=str(column_name),
                )

                candidates.append(
                    {
                        "record": self._normalize_db2_name(logical_record_name),
                        "physical_record": self._normalize_db2_name(physical_record_name),
                        "column": column_text,
                        "base": base,
                        "compact": self._compact_name(base),
                        "host": host,
                        "datatype": str(getattr(column, "datatype", "") or "").upper(),
                        "record_prefix": record_prefix,
                    }
                )

        return self._dedupe_candidates(candidates)

    def _logical_physical_records(
        self,
    ):
        pairs = []

        for logical_record_name, physical_record_name in self.record_table_map.items():
            logical = self._normalize_db2_name(str(logical_record_name))
            physical = self._normalize_db2_name(str(physical_record_name))

            if physical in self.records:
                pairs.append((logical, physical))

        for record_name in self.records.keys():
            normalized_record = self._normalize_db2_name(str(record_name))
            pairs.append((normalized_record, normalized_record))

        seen = set()
        result = []

        for pair in pairs:
            if pair in seen:
                continue

            seen.add(pair)
            result.append(pair)

        return result

    def _dominant_record_prefix(
        self,
        record,
    ) -> str:
        counts = {}

        for column_name in getattr(record, "fields", {}).keys():
            base = self._remove_generated_suffix(
                self._normalize_cobol_name(str(column_name)),
            )

            tokens = [
                token
                for token in base.split("-")
                if token
            ]

            if not tokens:
                continue

            first = tokens[0]
            counts[first] = counts.get(first, 0) + 1

        if not counts:
            return ""

        return sorted(
            counts.items(),
            key=lambda item: item[1],
            reverse=True,
        )[0][0]

    def _add_rewrite_aliases(
        self,
        rewrite_map,
        key: str,
        value: str,
        overwrite: bool,
    ) -> None:
        normalized = self._normalize_cobol_name(key)
        underscore = normalized.replace("-", "_")
        suffix_removed = self._remove_numeric_suffix(normalized)
        generated_removed = self._remove_generated_suffix(normalized)
        underscore_suffix_removed = suffix_removed.replace("-", "_")
        compact = self._compact_name(suffix_removed)

        aliases = [
            normalized,
            underscore,
            suffix_removed,
            generated_removed,
            underscore_suffix_removed,
            compact,
        ]

        for alias in aliases:
            if not alias:
                continue

            if overwrite:
                rewrite_map[alias] = value
            else:
                rewrite_map.setdefault(alias, value)

    def _protected_ranges(
        self,
        line: str,
    ):
        ranges = []

        for match in re.finditer(
            r"\bHV-[A-Z0-9-]+(?:$[0-9]+:[0-9]+$)?",
            line,
            flags=re.IGNORECASE,
        ):
            ranges.append((match.start(), match.end()))

        for match in re.finditer(
            r"\bNI-[A-Z0-9-]+\b",
            line,
            flags=re.IGNORECASE,
        ):
            ranges.append((match.start(), match.end()))

        for match in re.finditer(r"'[^']*'", line):
            ranges.append((match.start(), match.end()))

        for match in re.finditer(r'"[^"]*"', line):
            ranges.append((match.start(), match.end()))

        return ranges

    def _is_protected(
        self,
        start: int,
        end: int,
        ranges,
    ) -> bool:
        for range_start, range_end in ranges:
            if start >= range_start and end <= range_end:
                return True

        return False

    def _parse_legacy_token(
        self,
        token: str,
    ):
        normalized = self._normalize_cobol_name(token)
        suffix = self._extract_numeric_suffix(normalized)
        base = self._remove_numeric_suffix(normalized)

        return {
            "normalized": normalized,
            "base": base,
            "suffix": suffix,
        }

    def _date_part_type(
        self,
        token: str,
        tokens,
    ):
        token = str(token or "").upper()
        has_dy_dm_dd = "DY" in tokens and "DM" in tokens and "DD" in tokens

        if token in {"YEAR", "YR", "Y", "YY", "YYYY"}:
            return "YEAR"

        if token in {"MONTH", "MON", "MO", "M", "MM", "DM"}:
            return "MONTH"

        if token in {"DAY", "D", "DD"}:
            return "DAY"

        if token == "DY":
            if has_dy_dm_dd:
                return "YEAR"

            return "DAY"

        return None

    def _suffix_for_record(
        self,
        record_name: str,
    ):
        normalized_record = self._normalize_db2_name(record_name)

        for suffix, mapped_record in self.suffix_record_map.items():
            if mapped_record == normalized_record:
                return suffix

        return None

    def _host_variable(
        self,
        record_name: str,
        column_name: str,
    ) -> str:
        return (
            "HV-"
            + self._normalize_cobol_name(record_name)
            + "-"
            + self._normalize_cobol_name(column_name)
        )

    def _normalize_cobol_name(
        self,
        value: str,
    ) -> str:
        normalized = str(value or "").strip().upper()

        if not normalized:
            return ""

        normalized = normalized.replace("_", "-")
        normalized = normalized.replace(" ", "-")
        normalized = re.sub(r"[^A-Z0-9-]", "-", normalized)
        normalized = re.sub(r"-+", "-", normalized)

        return normalized.strip("-")

    def _normalize_db2_name(
        self,
        value: str,
    ) -> str:
        normalized = str(value or "").strip().upper()

        if not normalized:
            return ""

        normalized = normalized.replace("-", "_")
        normalized = normalized.replace(" ", "_")
        normalized = re.sub(r"[^A-Z0-9_]", "_", normalized)
        normalized = re.sub(r"_+", "_", normalized)

        return normalized.strip("_")

    def _normalize_host_name(
        self,
        value: str,
    ) -> str:
        normalized = str(value or "").strip().upper()

        if not normalized:
            return ""

        normalized = normalized.lstrip(":").strip()
        normalized = normalized.replace("_", "-")
        normalized = normalized.replace(" ", "-")
        normalized = re.sub(r"[^A-Z0-9\-():]", "-", normalized)
        normalized = re.sub(r"-+", "-", normalized)

        return normalized.strip("-")

    def _remove_numeric_suffix(
        self,
        value: str,
    ) -> str:
        normalized = self._normalize_cobol_name(value)

        return re.sub(r"-\d{4}$", "", normalized)

    def _remove_generated_suffix(
        self,
        value: str,
    ) -> str:
        normalized = self._normalize_cobol_name(value)
        normalized = re.sub(r"-479[A-Z0-9]+$", "", normalized)
        normalized = re.sub(r"-\d{4}$", "", normalized)

        return normalized

    def _extract_numeric_suffix(
        self,
        value: str,
    ):
        normalized = self._normalize_cobol_name(value)
        match = re.search(r"-(\d{4})$", normalized)

        if not match:
            return None

        return match.group(1)

    def _compact_name(
        self,
        value: str,
    ) -> str:
        return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())

    def _unique_values(
        self,
        values,
    ):
        result = []
        seen = set()

        for value in values:
            normalized = str(value or "").strip().upper()

            if not normalized:
                continue

            if normalized in seen:
                continue

            seen.add(normalized)
            result.append(normalized)

        return result

    def _dedupe_candidates(
        self,
        candidates,
    ):
        result = []
        seen = set()

        for candidate in candidates:
            key = (
                candidate.get("record", ""),
                candidate.get("column", ""),
            )

            if key in seen:
                continue

            seen.add(key)
            result.append(candidate)

        return result