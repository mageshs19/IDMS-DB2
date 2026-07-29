import re

from idms_modernizer.domain.schema_models import DataField
from idms_modernizer.services.name_normalizer import NameNormalizer


class SchemaPictureEnricher:
    """
    Enriches DataField objects using schema listing lines.

    Generic behavior only:
    - No business table names are hardcoded.
    - No specific record names are hardcoded.
    - PIC text is preserved as close to schema listing as possible.
    - If PDF extraction drops parentheses, PIC is reconstructed from usage and storage length.
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

    PIC_WITH_KEYWORD_PATTERN = re.compile(
        r"""
        \bPIC(?:TURE)?\s+
        (?P<pic>
            S?\s*9\s*$\s*\d+\s*$\s*V\s*9\s*$\s*\d+\s*$
            |
            S?\s*9\s*$\s*\d+\s*$\s*V\s*9+
            |
            S?\s*9+\s*V\s*9\s*$\s*\d+\s*$
            |
            S?\s*9+\s*V\s*9+
            |
            S?\s*9\s*$\s*\d+\s*$
            |
            S?\s*9+
            |
            X\s*$\s*\d+\s*$
            |
            X+
        )
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    PIC_ANYWHERE_PATTERN = re.compile(
        r"""
        (?P<pic>
            S?\s*9\s*$\s*\d+\s*$\s*V\s*9\s*$\s*\d+\s*$
            |
            S?\s*9\s*$\s*\d+\s*$\s*V\s*9+
            |
            S?\s*9+\s*V\s*9\s*$\s*\d+\s*$
            |
            S?\s*9+\s*V\s*9+
            |
            S?\s*9\s*$\s*\d+\s*$
            |
            S?\s*9+
            |
            X\s*$\s*\d+\s*$
            |
            X+
        )
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    def enrich(
        self,
        fields: list[DataField],
        lines: list[str],
    ) -> list[DataField]:
        print("USING SCHEMA PICTURE ENRICHER VERSION FULL-PIC-FORMAT-FIX")

        field_blocks = self.build_field_blocks(lines=lines)

        enriched_fields: list[DataField] = []

        for field in fields or []:
            field_name = getattr(field, "name", "") or ""

            block = self.find_block_for_field(
                field_name=field_name,
                field_blocks=field_blocks,
            )

            enriched_fields.append(
                self.enrich_field(
                    field=field,
                    block=block,
                )
            )

        return enriched_fields

    def build_field_blocks(
        self,
        lines: list[str],
    ) -> dict[str, str]:
        normalized_lines = self.normalize_lines(lines=lines)

        starts: list[tuple[int, str]] = []

        for index, line in enumerate(normalized_lines):
            match = self.FIELD_START_PATTERN.match(line)

            if not match:
                continue

            starts.append(
                (
                    index,
                    match.group("name").upper(),
                )
            )

        blocks: dict[str, str] = {}

        for index, item in enumerate(starts):
            start_index, field_name = item

            if index + 1 < len(starts):
                end_index = starts[index + 1][0]
            else:
                end_index = len(normalized_lines)

            block = " ".join(normalized_lines[start_index:end_index])
            normalized_field_name = NameNormalizer.normalize(field_name)

            if normalized_field_name:
                blocks[normalized_field_name] = block

        return blocks

    def normalize_lines(
        self,
        lines: list[str],
    ) -> list[str]:
        result: list[str] = []

        for line in lines or []:
            if not line:
                continue

            value = str(line)
            value = value.replace("\t", " ")
            value = value.replace("\u00a0", " ")
            value = value.replace("PICTURE.", "PICTURE")
            value = value.replace("PIC.", "PIC")

            value = re.sub(r"<[^>]+>", " ", value)
            value = re.sub(r"\s+", " ", value).strip()

            if value:
                result.append(value)

        return result

    def find_block_for_field(
        self,
        field_name: str,
        field_blocks: dict[str, str],
    ) -> str:
        normalized_name = NameNormalizer.normalize(field_name or "")

        if not normalized_name:
            return ""

        if normalized_name in field_blocks:
            return field_blocks[normalized_name]

        suffix_removed = self.remove_record_suffix(value=normalized_name)

        for block_name, block in field_blocks.items():
            if self.remove_record_suffix(block_name) == suffix_removed:
                return block

        return ""

    def enrich_field(
        self,
        field: DataField,
        block: str,
    ) -> DataField:
        if not block:
            return self.copy_field_with_defaults(field=field)

        usage = self.extract_usage(block=block)

        start_position, storage_length = self.extract_start_and_length(
            block=block,
        )

        picture_text = self.extract_picture(
            block=block,
            usage=usage,
            storage_length=storage_length,
            field=field,
        )

        datatype, logical_length, scale, clean_picture = self.derive_type_from_picture(
            field=field,
            picture=picture_text,
            usage=usage,
            storage_length=storage_length,
        )

        if self.is_date_field(
            field=field,
            picture=clean_picture,
            storage_length=storage_length,
            datatype=datatype,
        ):
            datatype = "DATE"
            logical_length = None
            scale = None
            clean_picture = clean_picture or picture_text

        end_position = None

        if start_position is not None and storage_length is not None:
            end_position = start_position + storage_length - 1

        return self.make_field(
            source=field,
            datatype=datatype,
            length=logical_length,
            scale=scale,
            picture=clean_picture,
            start_position=start_position,
            end_position=end_position,
            basetype=self.basetype_for_datatype(datatype=datatype),
        )

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

    def extract_usage(
        self,
        block: str,
    ) -> str:
        upper = str(block or "").upper()

        if "COMP-3" in upper:
            return "COMP-3"

        if re.search(r"\bCOMP\b", upper):
            return "COMP"

        usage_match = self.USAGE_PATTERN.search(block or "")

        if usage_match:
            return usage_match.group("usage").upper()

        return "DISPLAY"

    def extract_start_and_length(
        self,
        block: str,
    ) -> tuple[int | None, int | None]:
        match = self.START_LENGTH_PATTERN.search(block or "")

        if not match:
            return None, None

        return int(match.group("start")), int(match.group("length"))

    def extract_picture(
        self,
        block: str,
        usage: str,
        storage_length: int | None,
        field: DataField,
    ) -> str | None:
        if not block:
            return None

        picture_area = self.remove_trailing_start_and_length(value=block)

        keyword_matches = list(self.PIC_WITH_KEYWORD_PATTERN.finditer(picture_area))

        if keyword_matches:
            match = self.best_picture_match(keyword_matches)
            raw_picture = self.clean_picture(
                value=match.group("pic"),
                usage=usage,
            )

            return self.reconstruct_picture_if_needed(
                field=field,
                picture=raw_picture,
                usage=usage,
                storage_length=storage_length,
            )

        anywhere_matches = list(self.PIC_ANYWHERE_PATTERN.finditer(picture_area))

        if not anywhere_matches:
            return None

        match = self.best_picture_match(matches=anywhere_matches)

        raw_picture = self.clean_picture(
            value=match.group("pic"),
            usage=usage,
        )

        return self.reconstruct_picture_if_needed(
            field=field,
            picture=raw_picture,
            usage=usage,
            storage_length=storage_length,
        )

    def best_picture_match(
        self,
        matches,
    ):
        def score(match) -> tuple[int, int]:
            value = self.clean_picture(match.group("pic")) or ""
            core = self.picture_core(value)

            score_value = 0

            if "(" in core and ")" in core:
                score_value += 100

            if "V" in core:
                score_value += 50

            if core.startswith("S"):
                score_value += 10

            score_value += len(core)

            return score_value, match.start()

        return sorted(matches, key=score)[-1]

    def reconstruct_picture_if_needed(
        self,
        field: DataField,
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
            return self.format_picture_spacing(picture)

        if "V" in core:
            return self.format_picture_spacing(picture)

        if core == "X":
            if storage_length and storage_length > 1:
                return f"X({storage_length})"

            return self.format_picture_spacing(picture)

        if core in {"9", "S9"}:
            signed = core.startswith("S")

            if usage_upper == "COMP-3":
                precision = self.comp3_precision_from_storage(
                    storage_length=storage_length,
                )

                prefix = "S9" if signed else "9"

                return f"{prefix}({precision}) COMP-3"

            if storage_length and storage_length > 1:
                prefix = "S9" if signed else "9"

                return f"{prefix}({storage_length})"

            return self.format_picture_spacing(picture)

        return self.format_picture_spacing(picture)

    def comp3_precision_from_storage(
        self,
        storage_length: int | None,
    ) -> int:
        if not storage_length:
            return 1

        return max((int(storage_length) * 2) - 1, 1)

    def format_picture_spacing(
        self,
        picture: str | None,
    ) -> str | None:
        if not picture:
            return None

        text = str(picture).upper().strip()
        text = text.replace("COMP-3", " COMP-3")
        text = text.replace("COMP", " COMP")

        text = re.sub(r"\s+", " ", text).strip()

        return text

    def remove_trailing_start_and_length(
        self,
        value: str,
    ) -> str:
        return re.sub(
            r"\s+[0-9]+\s+[0-9]+\s*$",
            "",
            str(value or ""),
        ).strip()

    def clean_picture(
        self,
        value: str | None,
        usage: str | None = None,
    ) -> str | None:
        if not value:
            return None

        text = str(value).upper()
        text = re.sub(r"\s+", "", text)
        text = text.replace(".", "")

        if usage:
            usage_upper = usage.upper()

            if usage_upper in {"COMP", "COMP-3"} and usage_upper not in text:
                text = f"{text} {usage_upper}"

        return self.format_picture_spacing(text)

    def picture_core(
        self,
        picture: str | None,
    ) -> str:
        text = str(picture or "").upper()

        text = text.replace("COMP-3", "")
        text = text.replace("COMP", "")
        text = text.replace("DISPLAY", "")
        text = text.replace("PIC", "")
        text = text.replace("PICTURE", "")
        text = text.replace(" ", "")
        text = text.replace(".", "")

        return text

    def derive_type_from_picture(
        self,
        field: DataField,
        picture: str | None,
        usage: str,
        storage_length: int | None,
    ) -> tuple[str | None, int | None, int | None, str | None]:
        if not picture:
            if getattr(field, "has_child", False) or getattr(field, "is_group", False):
                return None, storage_length, None, None

            return getattr(field, "datatype", None), storage_length, None, None

        pic = self.clean_picture(
            value=picture,
            usage=usage,
        )

        core = self.picture_core(picture=pic)

        if not core:
            return None, storage_length, None, pic

        if self.picture_is_character(core):
            length = self.character_length(picture=core)
            return "CHAR", length, None, pic

        if self.picture_is_decimal(core):
            precision, scale = self.decimal_precision_scale(picture=core)
            return "DECIMAL", precision, scale, pic

        if self.picture_is_numeric(core):
            precision = self.numeric_precision(picture=core)
            return "DECIMAL", precision, 0, pic

        return None, storage_length, None, pic

    def picture_is_character(
        self,
        picture: str,
    ) -> bool:
        return bool(
            re.fullmatch(
                r"X+|X$\d+$",
                picture,
                flags=re.IGNORECASE,
            )
        )

    def character_length(
        self,
        picture: str,
    ) -> int:
        repeated = re.fullmatch(
            r"X$(\d+)$",
            picture,
            flags=re.IGNORECASE,
        )

        if repeated:
            return int(repeated.group(1))

        return picture.upper().count("X")

    def picture_is_numeric(
        self,
        picture: str,
    ) -> bool:
        return "9" in picture.upper()

    def picture_is_decimal(
        self,
        picture: str,
    ) -> bool:
        return "V" in picture.upper() and "9" in picture.upper()

    def decimal_precision_scale(
        self,
        picture: str,
    ) -> tuple[int, int]:
        pic = picture.upper().replace("S", "")
        before_v, after_v = pic.split("V", 1)

        integer_digits = self.count_9_digits(value=before_v)
        decimal_digits = self.count_9_digits(value=after_v)

        return integer_digits + decimal_digits, decimal_digits

    def numeric_precision(
        self,
        picture: str,
    ) -> int:
        pic = picture.upper().replace("S", "")

        if "V" in pic:
            before_v, after_v = pic.split("V", 1)
            return self.count_9_digits(before_v) + self.count_9_digits(after_v)

        return self.count_9_digits(value=pic)

    def count_9_digits(
        self,
        value: str,
    ) -> int:
        total = 0

        for match in re.finditer(
            r"9(?:$(\d+)$)?",
            value,
            flags=re.IGNORECASE,
        ):
            if match.group(1):
                total += int(match.group(1))
            else:
                total += 1

        return total

    def is_date_field(
        self,
        field: DataField,
        picture: str | None,
        storage_length: int | None,
        datatype: str | None,
    ) -> bool:
        name = NameNormalizer.normalize(getattr(field, "name", "") or "")
        normalized_name = name.replace(" ", "_")

        if datatype == "DATE":
            return True

        if normalized_name.endswith("_DATE"):
            return True

        if "_DATE_" in normalized_name:
            return True

        tokens = [token for token in re.split(r"[\s_]+", normalized_name) if token]

        if tokens and tokens[0] == "DA":
            return True

        if "DATE" in tokens:
            return True

        return False

    def basetype_for_datatype(
        self,
        datatype: str | None,
    ) -> str | None:
        if not datatype:
            return None

        datatype = datatype.upper()

        if datatype == "DATE":
            return "DATE"

        if datatype == "CHAR":
            return "TEXT"

        if datatype == "DECIMAL":
            return "NUMERIC"

        return datatype

    def remove_record_suffix(
        self,
        value: str,
    ) -> str:
        normalized = NameNormalizer.normalize(value or "")
        normalized = normalized.replace(" ", "_")

        return re.sub(r"_[0-9]{4}$", "", normalized)