import re

from idms_db2_converter.generators.naming import Naming
from idms_db2_converter.models import SchemaModel


class FieldRewriter:
    """
    Rewrites IDMS schema field references to DB2 host variables.

    Important rules:
    - Do NOT rewrite inside EXEC SQL ... END-EXEC blocks.
    - Do NOT rewrite comment lines.
    - Do NOT rewrite FILE SECTION / WORKING-STORAGE declarations.
    - Rewrite only PROCEDURE DIVISION executable COBOL lines.
    - Rewrite date parts using date_part_map when available.
    - Rewrite date parts generically when date_part_map is missing.
    - Rewrite normal IDMS fields using field_map.

    Generic date fallback example:
        START-YEAR-0415  -> HV-EMPLOYEE-START-DATE-0415(3:2)
        START-MONTH-0415 -> HV-EMPLOYEE-START-DATE-0415(6:2)
        START-DAY-0415   -> HV-EMPLOYEE-START-DATE-0415(9:2)
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

    IDMS_SCHEMA_FIELD = re.compile(
        r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d{4}\b",
        re.IGNORECASE,
    )

    DATE_PART_FIELD = re.compile(
        r"\b(?P<base>[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*)-(?P<part>YEAR|MONTH|DAY)-(?P<suffix>\d{4})\b",
        re.IGNORECASE,
    )

    DATE_PART_SUBSTRINGS = {
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
        schema: SchemaModel,
    ) -> None:
        self.schema = schema

    def rewrite(
        self,
        text: str,
    ) -> str:
        before_procedure, procedure = self.split_procedure_division(
            text,
        )

        if not procedure:
            return text

        procedure = self.rewrite_procedure_only(
            procedure,
        )

        return before_procedure + procedure

    def split_procedure_division(
        self,
        text: str,
    ) -> tuple[str, str]:
        match = self.PROCEDURE_DIVISION.search(
            text,
        )

        if not match:
            return text, ""

        return text[:match.start()], text[match.start():]

    def rewrite_procedure_only(
        self,
        procedure: str,
    ) -> str:
        output: list[str] = []
        in_exec_sql = False

        for line in procedure.splitlines():
            if self.EXEC_SQL_START.match(line):
                in_exec_sql = True
                output.append(line)
                continue

            if in_exec_sql:
                output.append(line)

                if self.EXEC_SQL_END.match(line):
                    in_exec_sql = False

                continue

            if self.COMMENT_LINE.match(line):
                output.append(line)
                continue

            rewritten = self.rewrite_line(
                line,
            )

            output.append(
                rewritten,
            )

        return "\n".join(output)

    def rewrite_line(
        self,
        line: str,
    ) -> str:
        line = self.rewrite_date_part_line(
            line,
        )

        line = self.rewrite_normal_field_line(
            line,
        )

        return line

    def rewrite_date_part_line(
        self,
        line: str,
    ) -> str:
        line = self.rewrite_date_part_using_metadata(
            line,
        )

        line = self.rewrite_date_part_using_generic_fallback(
            line,
        )

        return line

    def rewrite_date_part_using_metadata(
        self,
        line: str,
    ) -> str:
        date_part_map = getattr(
            self.schema,
            "date_part_map",
            {},
        )

        for idms_field in sorted(
            date_part_map.keys(),
            key=len,
            reverse=True,
        ):
            meta = date_part_map.get(
                idms_field,
            )

            if not meta:
                continue

            host = self.host_from_meta(
                meta,
            )

            if not host:
                continue

            substring_start = meta.get(
                "substring_start",
            )

            substring_length = meta.get(
                "substring_length",
            )

            if not substring_start or not substring_length:
                continue

            replacement = f"{host}({substring_start}:{substring_length})"

            for alias in self.hyphen_aliases(
                idms_field,
            ):
                line = self.replace_outside_literals(
                    line=line,
                    pattern=self.token_pattern(alias),
                    replacement=replacement,
                )

        return line

    def rewrite_date_part_using_generic_fallback(
        self,
        line: str,
    ) -> str:
        matches = list(
            self.DATE_PART_FIELD.finditer(line),
        )

        if not matches:
            return line

        rewritten = line

        for match in matches:
            full_field = match.group(0).upper()
            base = match.group("base").upper()
            part = match.group("part").upper()
            suffix = match.group("suffix").upper()

            meta = self.DATE_PART_SUBSTRINGS.get(
                part,
            )

            if not meta:
                continue

            date_field_candidates = self.date_field_candidates(
                base=base,
                suffix=suffix,
            )

            host = self.find_host_for_any_field(
                date_field_candidates,
            )

            if not host:
                continue

            replacement = (
                f"{host}"
                f"({meta['substring_start']}:{meta['substring_length']})"
            )

            rewritten = self.replace_outside_literals(
                line=rewritten,
                pattern=self.token_pattern(full_field),
                replacement=replacement,
            )

        return rewritten

    def date_field_candidates(
        self,
        base: str,
        suffix: str,
    ) -> list[str]:
        candidates: list[str] = []

        base_parts = base.split("-")

        candidates.append(
            f"{base}-DATE-{suffix}",
        )

        if base_parts:
            candidates.append(
                f"{'-'.join(base_parts)}-DATE-{suffix}",
            )

        if len(base_parts) > 1:
            candidates.append(
                f"{'-'.join(base_parts[:-1])}-DATE-{suffix}",
            )

        normalized: list[str] = []
        seen: set[str] = set()

        for candidate in candidates:
            value = candidate.upper()

            if value not in seen:
                seen.add(value)
                normalized.append(value)

        return normalized

    def find_host_for_any_field(
        self,
        field_names: list[str],
    ) -> str | None:
        field_map = getattr(
            self.schema,
            "field_map",
            {},
        )

        for field_name in field_names:
            aliases = self.hyphen_aliases(
                field_name,
            )

            for alias in aliases:
                meta = field_map.get(
                    alias.upper(),
                )

                if not meta:
                    continue

                host = self.host_from_meta(
                    meta,
                )

                if host:
                    return host

        for field_name in field_names:
            host = self.find_host_by_column_like_name(
                field_name,
            )

            if host:
                return host

        return None

    def find_host_by_column_like_name(
        self,
        field_name: str,
    ) -> str | None:
        normalized_field = self.normalize_token(
            field_name,
        )

        for record_name, record in getattr(self.schema, "records", {}).items():
            for column_name in getattr(record, "fields", {}).keys():
                normalized_column = self.normalize_token(
                    column_name,
                )

                if normalized_column == normalized_field:
                    return Naming.hv(
                        record_name,
                        column_name,
                    )

        return None

    def rewrite_normal_field_line(
        self,
        line: str,
    ) -> str:
        field_map = getattr(
            self.schema,
            "field_map",
            {},
        )

        for idms_field in sorted(
            field_map.keys(),
            key=len,
            reverse=True,
        ):
            meta = field_map.get(
                idms_field,
            )

            if not meta:
                continue

            host = self.host_from_meta(
                meta,
            )

            if not host:
                continue

            for alias in self.hyphen_aliases(
                idms_field,
            ):
                line = self.replace_outside_literals(
                    line=line,
                    pattern=self.token_pattern(alias),
                    replacement=host,
                )

        return line

    def host_from_meta(
        self,
        meta: dict,
    ) -> str | None:
        record = (
            meta.get("record")
            or meta.get("table")
            or meta.get("record_name")
            or meta.get("table_name")
        )

        column = (
            meta.get("column")
            or meta.get("field")
            or meta.get("column_name")
        )

        if record and column:
            return Naming.hv(
                str(record),
                str(column),
            )

        host = meta.get(
            "host",
        )

        if host:
            return str(host).upper()

        return None

    def hyphen_aliases(
        self,
        value: str,
    ) -> list[str]:
        raw = str(value).upper().strip()

        aliases = {
            raw,
            raw.replace("_", "-"),
            raw.replace("-", "_"),
        }

        return sorted(
            aliases,
            key=len,
            reverse=True,
        )

    def token_pattern(
        self,
        token: str,
    ) -> re.Pattern:
        return re.compile(
            rf"(?<![A-Z0-9_-]){re.escape(token)}(?![A-Z0-9_-])",
            re.IGNORECASE,
        )

    def replace_outside_literals(
        self,
        line: str,
        pattern: re.Pattern,
        replacement: str,
    ) -> str:
        parts = re.split(
            r"('[^']*')",
            line,
        )

        for index, part in enumerate(parts):
            if index % 2 == 1:
                continue

            parts[index] = pattern.sub(
                replacement,
                part,
            )

        return "".join(parts)

    def normalize_token(
        self,
        value: str,
    ) -> str:
        return (
            str(value)
            .upper()
            .replace("-", "_")
            .replace(" ", "_")
        )