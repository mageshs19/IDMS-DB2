import re

from idms_modernizer.domain.schema_models import DataField
from idms_modernizer.services.name_normalizer import NameNormalizer


print("LOADED SchemaPictureEnricher VERSION DEBUG-PIC-STRT-LGTH-2026-07-29")


class SchemaPictureEnricher:
    """
    Enriches DataField objects using schema listing lines.

    Rules implemented:
    - Build Excel IDMS PIC Clause from schema PICTURE + USAGE.
    - DISPLAY X(n) -> PIC X(n)
    - DISPLAY 9(n) -> PIC 9(n)
    - DISPLAY 9(n)V9(m) -> PIC 9(n)V9(m)
    - COMP-3 9(n) -> PIC 9(n) COMP-3
    - COMP-3 S9(n)V9(m) -> PIC S9(n)V9(m) COMP-3
    - COMP 9(n) -> PIC 9(n) COMP
    - Group items do not get PIC.
    - OCCURS does not change PIC.
    - Keys do not change PIC.
    - END = STRT + LGTH - 1.
    """

    FIELD_START_PATTERN = re.compile(
        r"^\s*(?P<level>0[1-9]|[1-4][0-9]|88)\s+"
        r"(?P<name>[A-Z][A-Z0-9-]*|FILLER)\b"
        r"(?P<rest>.*)$",
        re.IGNORECASE,
    )

    USAGE_PATTERN = re.compile(
        r"\b(?:USAGE\s+IS\s+)?(?P<usage>DISPLAY|COMP-3|COMP)\b",
        re.IGNORECASE,
    )

    START_LENGTH_PATTERN = re.compile(
        r"\b(?P<start>[0-9]+)\s+(?P<length>[0-9]+)\s*$",
        re.IGNORECASE,
    )

    PIC_PATTERNS = [
        re.compile(
            r"S?\s*9\s*$\s*\d+\s*$\s*V\s*9\s*$\s*\d+\s*$",
            re.IGNORECASE,
        ),
        re.compile(
            r"S?\s*9\s*$\s*\d+\s*$\s*V\s*9+",
            re.IGNORECASE,
        ),
        re.compile(
            r"S?\s*9+\s*V\s*9\s*$\s*\d+\s*$",
            re.IGNORECASE,
        ),
        re.compile(
            r"S?\s*9+\s*V\s*9+",
            re.IGNORECASE,
        ),
        re.compile(
            r"S?\s*9\s*$\s*\d+\s*$",
            re.IGNORECASE,
        ),
        re.compile(
            r"S?\s*9+",
            re.IGNORECASE,
        ),
        re.compile(
            r"X\s*$\s*\d+\s*$",
            re.IGNORECASE,
        ),
        re.compile(
            r"X+",
            re.IGNORECASE,
        ),
    ]

    DATE_NAME_TOKENS = {
        "DA",
        "DATE",
        "DT",
        "DTE",
        "YYMMDD",
        "YYYYMMDD",
        "YMD",
    }

    YEAR_PARTS = {
        "YEAR",
        "YR",
        "Y",
        "YY",
        "YYYY",
        "DY",
    }

    MONTH_PARTS = {
        "MONTH",
        "MON",
        "MO",
        "M",
        "MM",
        "DM",
    }

    DAY_PARTS = {
        "DAY",
        "D",
        "DD",
    }

    def enrich(
        self,
        fields: list[DataField],
        lines: list[str],
        debug_label: str = "",
    ) -> list[DataField]:
        print(
            "USING SchemaPictureEnricher.enrich VERSION DEBUG-PIC-STRT-LGTH-2026-07-29",
            f"debug_label={debug_label}",
        )

        normalized_lines = self.normalize_lines(
            lines=lines,
        )

        print(
            "SCHEMA_ENRICH_DEBUG_LINES",
            f"debug_label={debug_label}",
            f"line_count={len(normalized_lines)}",
        )

        for index, line in enumerate(normalized_lines[:80]):
            print(
                "SCHEMA_LINE_DEBUG",
                f"debug_label={debug_label}",
                f"index={index}",
                f"line={repr(line)}",
            )

        field_blocks = self.build_field_blocks(
            normalized_lines=normalized_lines,
            debug_label=debug_label,
        )

        enriched_fields: list[DataField] = []

        for field in fields or []:
            field_name = getattr(field, "name", "") or ""

            block = self.find_block_for_field(
                field_name=field_name,
                field_blocks=field_blocks,
            )

            if not block:
                print(
                    "SCHEMA_ENRICH_NO_BLOCK",
                    f"debug_label={debug_label}",
                    f"field={repr(field_name)}",
                )

                enriched_fields.append(
                    self.copy_field_with_defaults(
                        field=field,
                    )
                )
                continue

            enriched = self.enrich_field(
                field=field,
                block=block,
                debug_label=debug_label,
            )

            enriched_fields.append(enriched)

        enriched_fields = self.enrich_group_positions_from_children(
            fields=enriched_fields,
            debug_label=debug_label,
        )

        return enriched_fields

    def normalize_lines(
        self,
        lines: list[str],
    ) -> list[str]:
        result: list[str] = []

        for line in lines or []:
            if line is None:
                continue

            value = getattr(line, "text", None)

            if value is None:
                value = str(line)

            value = str(value)
            value = value.replace("\t", " ")
            value = value.replace("\u00a0", " ")
            value = value.replace("PICTURE .", "PICTURE")
            value = value.replace("PIC .", "PIC")
            value = re.sub(r"<[^>]+>", " ", value)
            value = re.sub(r"\s+", " ", value).strip()

            if value:
                result.append(value)

        return result

    def build_field_blocks(
        self,
        normalized_lines: list[str],
        debug_label: str = "",
    ) -> dict[str, str]:
        starts: list[tuple[int, str]] = []

        for index, line in enumerate(normalized_lines or []):
            match = self.FIELD_START_PATTERN.match(line)

            if not match:
                continue

            field_name = match.group("name") or ""

            starts.append(
                (
                    index,
                    field_name.upper(),
                )
            )

        print(
            "SCHEMA_BLOCK_STARTS_DEBUG",
            f"debug_label={debug_label}",
            f"starts_count={len(starts)}",
            f"starts={starts[:80]}",
        )

        blocks: dict[str, str] = {}

        for index, item in enumerate(starts):
            start_index, field_name = item

            if index + 1 < len(starts):
                end_index = starts[index + 1][0]
            else:
                end_index = len(normalized_lines)

            block = " ".join(
                normalized_lines[start_index:end_index],
            )

            normalized_field_name = NameNormalizer.normalize(
                field_name,
            )

            if normalized_field_name:
                blocks[normalized_field_name] = block

                suffix_removed = self.remove_record_suffix(
                    value=normalized_field_name,
                )

                if suffix_removed:
                    blocks.setdefault(
                        suffix_removed,
                        block,
                    )

                print(
                    "SCHEMA_BLOCK_DEBUG",
                    f"debug_label={debug_label}",
                    f"field={repr(normalized_field_name)}",
                    f"block={repr(block)}",
                )

        return blocks

    def find_block_for_field(
        self,
        field_name: str,
        field_blocks: dict[str, str],
    ) -> str:
        normalized_name = NameNormalizer.normalize(
            field_name or "",
        )

        if not normalized_name:
            return ""

        if normalized_name in field_blocks:
            return field_blocks[normalized_name]

        suffix_removed = self.remove_record_suffix(
            value=normalized_name,
        )

        if suffix_removed in field_blocks:
            return field_blocks[suffix_removed]

        for block_name, block in field_blocks.items():
            if self.remove_record_suffix(block_name) == suffix_removed:
                return block

        return ""

    def enrich_field(
        self,
        field: DataField,
        block: str,
        debug_label: str = "",
    ) -> DataField:
        field_name = getattr(field, "name", "") or ""

        if not block:
            return self.copy_field_with_defaults(field=field)

        parsed_line = self.parse_schema_block(
            block=block,
            field_name=field_name,
            debug_label=debug_label,
        )

        usage = parsed_line["usage"]
        start_position = parsed_line["start_position"]
        storage_length = parsed_line["storage_length"]
        picture_core = parsed_line["picture_core"]

        is_group = bool(
            getattr(field, "has_child", False)
            or getattr(field, "is_group", False)
        )

        if is_group:
            print(
                "SCHEMA_ENRICH_GROUP",
                f"debug_label={debug_label}",
                f"field={repr(field_name)}",
                f"start={start_position}",
                f"length={storage_length}",
                f"picture=None",
            )

            return self.make_field(
                source=field,
                datatype=getattr(field, "datatype", None),
                length=storage_length or getattr(field, "length", None),
                scale=getattr(field, "scale", None),
                picture=None,
                start_position=start_position or getattr(field, "start_position", None),
                end_position=self.calculate_end_position(
                    start_position=start_position,
                    storage_length=storage_length,
                    fallback=getattr(field, "end_position", None),
                ),
                basetype=getattr(field, "basetype", None),
            )

        rendered_picture = self.render_cobol_pic_clause(
            picture=picture_core,
            usage=usage,
            storage_length=storage_length,
        )

        datatype, logical_length, scale = self.derive_type_from_picture(
            picture=rendered_picture,
            usage=usage,
            storage_length=storage_length,
            fallback_datatype=getattr(field, "datatype", None),
        )

        if self.is_date_field(
            field=field,
            picture=rendered_picture,
            storage_length=storage_length,
            datatype=datatype,
        ):
            datatype = "DATE"
            scale = None

        end_position = self.calculate_end_position(
            start_position=start_position,
            storage_length=storage_length,
            fallback=getattr(field, "end_position", None),
        )

        actual_length = storage_length

        if actual_length is None:
            actual_length = logical_length

        print(
            "SCHEMA_ENRICH_RESULT",
            f"debug_label={debug_label}",
            f"field={repr(field_name)}",
            f"usage={repr(usage)}",
            f"picture_core={repr(picture_core)}",
            f"rendered_picture={repr(rendered_picture)}",
            f"datatype={repr(datatype)}",
            f"length={actual_length}",
            f"scale={scale}",
            f"start={start_position}",
            f"end={end_position}",
        )

        return self.make_field(
            source=field,
            datatype=datatype,
            length=actual_length,
            scale=scale,
            picture=rendered_picture,
            start_position=start_position,
            end_position=end_position,
            basetype=self.basetype_for_datatype(
                datatype=datatype,
            ),
        )

    def parse_schema_block(
        self,
        block: str,
        field_name: str,
        debug_label: str = "",
    ) -> dict:
        text = str(block or "").strip()

        usage = self.extract_usage(
            block=text,
        )

        start_position, storage_length = self.extract_start_and_length(
            block=text,
        )

        body_without_positions = self.remove_trailing_start_and_length(
            value=text,
        )

        rest = self.extract_rest_after_level_and_name(
            block=body_without_positions,
        )

        picture_area = self.remove_usage_words(
            value=rest,
        )

        picture_area = self.remove_schema_noise(
            value=picture_area,
        )

        picture_core = self.extract_picture_core(
            value=picture_area,
        )

        print(
            "SCHEMA_PARSE_DEBUG",
            f"debug_label={debug_label}",
            f"field={repr(field_name)}",
            f"block={repr(block)}",
            f"usage={repr(usage)}",
            f"start={start_position}",
            f"length={storage_length}",
            f"rest={repr(rest)}",
            f"picture_area={repr(picture_area)}",
            f"picture_core={repr(picture_core)}",
        )

        return {
            "usage": usage,
            "start_position": start_position,
            "storage_length": storage_length,
            "picture_core": picture_core,
        }

    def extract_rest_after_level_and_name(
        self,
        block: str,
    ) -> str:
        match = self.FIELD_START_PATTERN.match(
            block or "",
        )

        if not match:
            return str(block or "")

        return str(match.group("rest") or "").strip()

    def extract_usage(
        self,
        block: str,
    ) -> str:
        upper = str(block or "").upper()

        if "COMP-3" in upper:
            return "COMP-3"

        if re.search(r"\bCOMP\b", upper):
            return "COMP"

        usage_match = self.USAGE_PATTERN.search(
            block or "",
        )

        if usage_match:
            return usage_match.group("usage").upper()

        return "DISPLAY"

    def extract_start_and_length(
        self,
        block: str,
    ) -> tuple[int | None, int | None]:
        match = self.START_LENGTH_PATTERN.search(
            block or "",
        )

        if not match:
            return None, None

        return int(match.group("start")), int(match.group("length"))

    def remove_trailing_start_and_length(
        self,
        value: str,
    ) -> str:
        return re.sub(
            r"\b[0-9]+\s+[0-9]+\s*$",
            "",
            str(value or ""),
        ).strip()

    def remove_usage_words(
        self,
        value: str,
    ) -> str:
        text = str(value or "")

        text = re.sub(r"\bUSAGE\s+IS\s+COMP-3\b", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\bUSAGE\s+IS\s+COMP\b", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\bUSAGE\s+IS\s+DISPLAY\b", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\bCOMP-3\b", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\bCOMP\b", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\bDISPLAY\b", " ", text, flags=re.IGNORECASE)

        return re.sub(r"\s+", " ", text).strip()

    def remove_schema_noise(
        self,
        value: str,
    ) -> str:
        text = str(value or "")

        text = re.sub(r"\bOCCURS\b.*$", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\bREDEFINES\b.*$", " ", text, flags=re.IGNORECASE)
        text = text.replace(".", " ")
        text = text.replace("\u00a0", " ")
        text = text.replace("\t", " ")

        return re.sub(r"\s+", " ", text).strip()

    def extract_picture_core(
        self,
        value: str,
    ) -> str | None:
        text = str(value or "").upper()

        candidates: list[tuple[int, int, str]] = []

        for pattern in self.PIC_PATTERNS:
            for match in pattern.finditer(text):
                raw = match.group(0)
                core = self.clean_picture_core(raw)

                if not core:
                    continue

                score = self.picture_score(
                    core=core,
                )

                candidates.append(
                    (
                        score,
                        match.start(),
                        core,
                    )
                )

        if not candidates:
            return None

        candidates.sort(
            key=lambda item: (item[0], item[1]),
        )

        return candidates[-1][2]

    def picture_score(
        self,
        core: str,
    ) -> int:
        text = str(core or "").upper()

        score = 0

        if "(" in text and ")" in text:
            score += 100

        if "V" in text:
            score += 50

        if text.startswith("S"):
            score += 10

        if text.startswith("X"):
            score += 5

        score += len(text)

        return score

    def clean_picture_core(
        self,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        text = str(value).upper()
        text = text.replace("PICTURE", "")
        text = text.replace("PIC", "")
        text = text.replace(".", "")
        text = text.replace("\u00a0", " ")
        text = text.replace("\t", " ")
        text = re.sub(r"\s+", "", text)

        return text.strip() or None

    def render_cobol_pic_clause(
        self,
        picture: str | None,
        usage: str,
        storage_length: int | None,
    ) -> str | None:
        if not picture:
            return None

        normalized_picture = self.reconstruct_picture_if_needed(
            picture=picture,
            usage=usage,
            storage_length=storage_length,
        )

        if not normalized_picture:
            return None

        normalized_picture = self.format_picture_spacing(
            picture=normalized_picture,
        )

        if not normalized_picture:
            return None

        usage_upper = str(usage or "DISPLAY").upper()

        if usage_upper in {"COMP", "COMP-3"}:
            if usage_upper not in normalized_picture.upper():
                normalized_picture = f"{normalized_picture} {usage_upper}"

        if normalized_picture.upper().startswith("PIC "):
            return normalized_picture

        return f"PIC {normalized_picture}"

    def reconstruct_picture_if_needed(
        self,
        picture: str | None,
        usage: str,
        storage_length: int | None,
    ) -> str | None:
        if not picture:
            return None

        usage_upper = str(usage or "").upper()
        core = self.picture_core(picture)

        if not core:
            return picture

        if "(" in core and ")" in core:
            return self.format_picture_spacing(core)

        if "V" in core:
            return self.format_picture_spacing(core)

        if core == "X":
            if storage_length and storage_length > 1:
                return f"X({storage_length})"

            return "X"

        if core in {"9", "S9"}:
            signed = core.startswith("S")

            if usage_upper == "COMP-3":
                precision = self.comp3_precision_from_storage(
                    storage_length=storage_length,
                )

                if precision:
                    return f"{'S' if signed else ''}9({precision})"

            if storage_length and storage_length > 1:
                return f"{'S' if signed else ''}9({storage_length})"

            return core

        return self.format_picture_spacing(core)

    def comp3_precision_from_storage(
        self,
        storage_length: int | None,
    ) -> int | None:
        if storage_length is None:
            return None

        try:
            length = int(storage_length)
        except Exception:
            return None

        if length <= 0:
            return None

        return (length * 2) - 1

    def format_picture_spacing(
        self,
        picture: str | None,
    ) -> str | None:
        if not picture:
            return None

        text = str(picture).upper().strip()
        text = text.replace("\u00a0", " ")
        text = text.replace("\t", " ")
        text = re.sub(r"\s+", "", text)

        text = text.replace("COMP-3", " COMP-3")
        text = re.sub(r"\bCOMP\b", " COMP", text)
        text = re.sub(r"\s+", " ", text).strip()

        return text

    def derive_type_from_picture(
        self,
        picture: str | None,
        usage: str,
        storage_length: int | None,
        fallback_datatype: str | None,
    ) -> tuple[str | None, int | None, int | None]:
        if not picture:
            return fallback_datatype, storage_length, None

        core = self.picture_core(
            picture=picture,
        )

        if not core:
            return fallback_datatype, storage_length, None

        if self.picture_is_character(core):
            length = self.character_length(
                picture=core,
            )
            return "CHAR", length, None

        if self.picture_is_decimal(core):
            precision, scale = self.decimal_precision_scale(
                picture=core,
            )
            return "DECIMAL", precision, scale

        if self.picture_is_numeric(core):
            precision = self.numeric_precision(
                picture=core,
            )
            return "DECIMAL", precision, 0

        return fallback_datatype, storage_length, None

    def picture_core(
        self,
        picture: str | None,
    ) -> str:
        text = str(picture or "").upper()
        text = text.replace("PICTURE", "")
        text = text.replace("PIC", "")
        text = text.replace("COMP-3", "")
        text = re.sub(r"\bCOMP\b", "", text)
        text = text.replace("DISPLAY", "")
        text = text.replace("USAGE", "")
        text = text.replace("IS", "")
        text = text.replace(".", "")
        text = re.sub(r"\s+", "", text)

        return text.strip()

    def picture_is_character(
        self,
        picture: str,
    ) -> bool:
        text = str(picture or "").upper()

        if text.startswith("X(") and text.endswith(")"):
            return self.extract_parenthesized_int(text) is not None

        return bool(text) and set(text) == {"X"}

    def character_length(
        self,
        picture: str,
    ) -> int:
        text = str(picture or "").upper()

        if text.startswith("X(") and text.endswith(")"):
            parsed = self.extract_parenthesized_int(text)

            if parsed is not None:
                return parsed

        return text.count("X")

    def picture_is_numeric(
        self,
        picture: str,
    ) -> bool:
        text = str(picture or "").upper()

        if text.startswith("S"):
            text = text[1:]

        return "9" in text and "V" not in text

    def picture_is_decimal(
        self,
        picture: str,
    ) -> bool:
        text = str(picture or "").upper()

        if text.startswith("S"):
            text = text[1:]

        return "V" in text and "9" in text

    def decimal_precision_scale(
        self,
        picture: str,
    ) -> tuple[int, int]:
        text = str(picture or "").upper()

        if text.startswith("S"):
            text = text[1:]

        before_v, after_v = text.split("V", 1)

        integer_digits = self.count_9_digits(
            value=before_v,
        )
        decimal_digits = self.count_9_digits(
            value=after_v,
        )

        return integer_digits + decimal_digits, decimal_digits

    def numeric_precision(
        self,
        picture: str,
    ) -> int:
        text = str(picture or "").upper()

        if text.startswith("S"):
            text = text[1:]

        return self.count_9_digits(
            value=text,
        )

    def count_9_digits(
        self,
        value: str,
    ) -> int:
        text = str(value or "").upper()

        if text.startswith("S"):
            text = text[1:]

        total = 0
        index = 0

        while index < len(text):
            if text[index] != "9":
                index += 1
                continue

            if index + 1 < len(text) and text[index + 1] == "(":
                close_index = text.find(")", index + 2)

                if close_index != -1:
                    number_text = text[index + 2:close_index]

                    if number_text.isdigit():
                        total += int(number_text)
                        index = close_index + 1
                        continue

            total += 1
            index += 1

        return total

    def extract_parenthesized_int(
        self,
        value: str,
    ) -> int | None:
        text = str(value or "")

        open_index = text.find("(")

        if open_index == -1:
            return None

        close_index = text.find(")", open_index + 1)

        if close_index == -1:
            return None

        number_text = text[open_index + 1:close_index].strip()

        if not number_text.isdigit():
            return None

        return int(number_text)

    def calculate_end_position(
        self,
        start_position: int | None,
        storage_length: int | None,
        fallback=None,
    ) -> int | None:
        try:
            if start_position is not None and storage_length is not None:
                return int(start_position) + int(storage_length) - 1
        except Exception:
            pass

        try:
            if fallback is not None:
                return int(fallback)
        except Exception:
            pass

        return None

    def is_date_field(
        self,
        field: DataField,
        picture: str | None,
        storage_length: int | None,
        datatype: str | None,
    ) -> bool:
        datatype_upper = str(datatype or "").upper()

        if datatype_upper == "DATE":
            return True

        field_name = NameNormalizer.normalize(
            getattr(field, "name", "") or "",
        )

        parts = [
            part
            for part in field_name.replace("-", " ").replace("_", " ").split()
            if part
        ]

        if "DATE" in parts or "DA" in parts:
            if storage_length == 8:
                return True

        core = self.picture_core(
            picture=picture,
        )

        if core in {"9(8)", "S9(8)", "99999999", "S99999999"}:
            if field_name.startswith("DA ") or " DATE" in field_name:
                return True

        return False

    def basetype_for_datatype(
        self,
        datatype: str | None,
    ) -> str | None:
        datatype_upper = str(datatype or "").upper()

        if datatype_upper == "DATE":
            return "DATE"

        if datatype_upper in {"DECIMAL", "NUMERIC", "INTEGER"}:
            return "NUMERIC"

        if datatype_upper in {"CHAR", "VARCHAR"}:
            return "CHAR"

        return datatype

    def enrich_group_positions_from_children(
        self,
        fields: list[DataField],
        debug_label: str = "",
    ) -> list[DataField]:
        output = list(fields or [])

        for index, field in enumerate(output):
            is_group = bool(
                getattr(field, "has_child", False)
                or getattr(field, "is_group", False)
            )

            if not is_group:
                continue

            level = getattr(field, "level", None)

            try:
                parent_level = int(level)
            except Exception:
                continue

            child_starts: list[int] = []
            child_ends: list[int] = []

            for child in output[index + 1:]:
                child_level = getattr(child, "level", None)

                try:
                    current_level = int(child_level)
                except Exception:
                    continue

                if current_level <= parent_level:
                    break

                start = getattr(child, "start_position", None)
                end = getattr(child, "end_position", None)

                if start is not None:
                    try:
                        child_starts.append(int(start))
                    except Exception:
                        pass

                if end is not None:
                    try:
                        child_ends.append(int(end))
                    except Exception:
                        pass

            if not child_starts and not child_ends:
                continue

            group_start = min(child_starts) if child_starts else getattr(field, "start_position", None)
            group_end = max(child_ends) if child_ends else getattr(field, "end_position", None)

            group_length = getattr(field, "length", None)

            try:
                if group_start is not None and group_end is not None:
                    group_length = int(group_end) - int(group_start) + 1
            except Exception:
                pass

            print(
                "SCHEMA_GROUP_POSITION_DEBUG",
                f"debug_label={debug_label}",
                f"group={repr(getattr(field, 'name', None))}",
                f"start={group_start}",
                f"length={group_length}",
                f"end={group_end}",
            )

            output[index] = self.make_field(
                source=field,
                datatype=getattr(field, "datatype", None),
                length=group_length,
                scale=getattr(field, "scale", None),
                picture=None,
                start_position=group_start,
                end_position=group_end,
                basetype=getattr(field, "basetype", None),
            )

        return output

    def copy_field_with_defaults(
        self,
        field: DataField,
    ) -> DataField:
        return self.make_field(
            source=field,
            datatype=getattr(field, "datatype", None),
            length=getattr(field, "length", None),
            scale=getattr(field, "scale", None),
            picture=getattr(field, "picture", None),
            start_position=getattr(field, "start_position", None),
            end_position=getattr(field, "end_position", None),
            basetype=getattr(field, "basetype", None),
        )

    def make_field(
        self,
        source: DataField,
        datatype: str | None,
        length: int | None,
        scale: int | None,
        picture: str | None,
        start_position: int | None,
        end_position: int | None,
        basetype: str | None,
    ) -> DataField:
        data = source.model_dump()

        data.update(
            {
                "datatype": datatype,
                "length": length,
                "scale": scale,
                "picture": picture,
                "start_position": start_position,
                "end_position": end_position,
                "basetype": basetype,
            }
        )

        return DataField(**data)

    def remove_record_suffix(
        self,
        value: str,
    ) -> str:
        text = str(value or "").strip().upper()
        text = re.sub(r"[\s_-]+[0-9]{4}$", "", text)
        text = re.sub(r"[0-9]{4}$", "", text)
        text = re.sub(r"[\s_-]+$", "", text)

        return text