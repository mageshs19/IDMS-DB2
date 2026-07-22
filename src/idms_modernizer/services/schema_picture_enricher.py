import re

from idms_modernizer.domain.schema_models import DataField


class SchemaPictureEnricher:
    """
    Fast schema picture enricher.

    Behavior:
    - Preserves DataField.level from FieldExtractor.
    - Does not use hardcoded business field names.
    - Datatype is derived from PIC clause and USAGE only.
    - Captures start position, storage length, field end position, and basetype.
    - Infers DATE groups generically from date-like group structure and byte length.

    Rules:
    - X / X(n) -> CHAR / VARCHAR
    - 9 / 9(n) / S9 / S9(n) -> SMALLINT / INTEGER / BIGINT
    - Decimal PIC with V -> DECIMAL
    - COMP / COMP-3 respected generically
    """

    FIELD_START_PATTERN = re.compile(
        r"^\s*(?P<level>0[1-9]|[1-4][0-9]|88)\s+"
        r"(?P<name>[A-Z][A-Z0-9-]*|FILLER)\b"
        r"(?P<rest>.*)$",
        re.IGNORECASE,
    )

    USAGE_PATTERN = re.compile(
        r"\b(DISPLAY|COMP-3|COMP)\b",
        re.IGNORECASE,
    )

    START_LENGTH_PATTERN = re.compile(
        r"\b(?P<start>[0-9]+)\s+(?P<length>[0-9]+)\s*$",
        re.IGNORECASE,
    )

    X_PAREN = re.compile(
        r"\bX\s*$\s*(?P<length>[0-9]+)\s*$",
        re.IGNORECASE,
    )

    NINE_PAREN = re.compile(
        r"\bS?9\s*$\s*(?P<digits>[0-9]+)\s*$",
        re.IGNORECASE,
    )

    DECIMAL_PAREN = re.compile(
        r"\b(?P<int_part>S?9)\s*$\s*(?P<int_digits>[0-9]+)\s*$"
        r"\s*V\s*9\s*$\s*(?P<dec_digits>[0-9]+)\s*$",
        re.IGNORECASE,
    )

    DECIMAL_INLINE = re.compile(
        r"\b(?P<int_part>S?9+)\s*V\s*(?P<dec_part>9+)\b",
        re.IGNORECASE,
    )

    SIGNED_FRACTION = re.compile(
        r"\bS?V(?P<dec_part>9+)\b",
        re.IGNORECASE,
    )

    INLINE_X = re.compile(
        r"\bX+\b",
        re.IGNORECASE,
    )

    INLINE_9 = re.compile(
        r"\bS?9+\b",
        re.IGNORECASE,
    )

    def enrich(
        self,
        fields: list[DataField],
        lines: list[str],
    ) -> list[DataField]:
        print("USING SCHEMA PICTURE ENRICHER VERSION GENERIC-NO-NAME-RULES-WITH-LEVEL")

        cleaned_lines = self.clean_lines(
            lines=lines,
        )

        field_blocks = self.build_field_blocks(
            lines=cleaned_lines,
        )

        enriched: list[DataField] = []

        for field in fields:
            if not field or not field.name:
                continue

            block = field_blocks.get(
                field.name.upper(),
                "",
            )

            enriched.append(
                self.enrich_field(
                    field=field,
                    block=block,
                )
            )

        return enriched

    def clean_lines(
        self,
        lines: list[str],
    ) -> list[str]:
        result: list[str] = []

        for line in lines:
            if not line:
                continue

            value = str(line)

            value = value.replace(
                "\t",
                " ",
            )

            value = value.replace(
                "\u00a0",
                " ",
            )

            value = value.replace(
                "PICTURE . ",
                "PICTURE ",
            )

            value = value.replace(
                "PIC. ",
                "PIC ",
            )

            value = re.sub(
                r"<[^>]+>",
                " ",
                value,
            )

            value = re.sub(
                r"\s+",
                " ",
                value,
            ).strip()

            if value:
                result.append(value)

        return result

    def build_field_blocks(
        self,
        lines: list[str],
    ) -> dict[str, str]:
        starts: list[tuple[int, str]] = []

        for index, line in enumerate(lines):
            match = self.FIELD_START_PATTERN.match(
                line,
            )

            if not match:
                continue

            field_name = match.group("name").upper()

            starts.append(
                (
                    index,
                    field_name,
                )
            )

        blocks: dict[str, str] = {}

        for index, item in enumerate(starts):
            start_index, field_name = item

            if index + 1 < len(starts):
                end_index = starts[index + 1][0]
            else:
                end_index = len(lines)

            if field_name == "FILLER":
                continue

            block = " ".join(
                lines[start_index:end_index],
            )

            if field_name not in blocks:
                blocks[field_name] = block

        return blocks

    def enrich_field(
        self,
        field: DataField,
        block: str,
    ) -> DataField:
        if not block:
            return self.copy_field_with_defaults(
                field=field,
            )

        usage = self.extract_usage(
            block=block,
        )

        start_position, storage_length = self.extract_start_and_length(
            block=block,
        )

        picture_block = self.remove_trailing_start_and_length(
            block=block,
        )

        if self.is_date_group(
            field_name=field.name,
            block=picture_block,
            storage_length=storage_length,
        ):
            return self.make_field(
                name=field.name,
                level=getattr(field, "level", None),
                datatype="DATE",
                length=None,
                scale=None,
                picture=None,
                start_position=start_position,
                storage_length=storage_length,
            )

        datatype, length, scale, picture = self.parse_block(
            block=picture_block,
            usage=usage,
            storage_length=storage_length,
        )

        return self.make_field(
            name=field.name,
            level=getattr(field, "level", None),
            datatype=datatype,
            length=length,
            scale=scale,
            picture=picture,
            start_position=start_position,
            storage_length=storage_length,
        )

    def copy_field_with_defaults(
        self,
        field: DataField,
    ) -> DataField:
        return DataField(
            name=field.name,
            level=getattr(field, "level", None),
            datatype=field.datatype,
            length=field.length,
            scale=field.scale,
            picture=field.picture,
            start_position=getattr(field, "start_position", None),
            end_position=getattr(field, "end_position", None),
            basetype=getattr(
                field,
                "basetype",
                self.derive_basetype(field.datatype),
            ),
        )

    def make_field(
        self,
        name: str,
        level: int | None,
        datatype: str | None,
        length: int | None,
        scale: int | None,
        picture: str | None,
        start_position: int | None,
        storage_length: int | None,
    ) -> DataField:
        end_position = None

        if start_position is not None and storage_length is not None:
            end_position = start_position + storage_length - 1

        return DataField(
            name=name,
            level=level,
            datatype=datatype,
            length=length,
            scale=scale,
            picture=picture,
            start_position=start_position,
            end_position=end_position,
            basetype=self.derive_basetype(
                datatype=datatype,
            ),
        )

    def extract_usage(
        self,
        block: str,
    ) -> str:
        upper = block.upper()

        if "COMP-3" in upper:
            return "COMP-3"

        if re.search(
            r"\bCOMP\b",
            upper,
        ):
            return "COMP"

        return "DISPLAY"

    def extract_start_and_length(
        self,
        block: str,
    ) -> tuple[int | None, int | None]:
        cleaned = self.clean_text(
            value=block,
        )

        match = self.START_LENGTH_PATTERN.search(
            cleaned,
        )

        if not match:
            return None, None

        try:
            return (
                int(match.group("start")),
                int(match.group("length")),
            )
        except Exception:
            return None, None

    def extract_storage_length(
        self,
        block: str,
    ) -> int | None:
        _, storage_length = self.extract_start_and_length(
            block=block,
        )

        return storage_length

    def remove_trailing_start_and_length(
        self,
        block: str,
    ) -> str:
        cleaned = self.clean_text(
            value=block,
        )

        return self.START_LENGTH_PATTERN.sub(
            "",
            cleaned,
        ).strip()

    def is_date_group(
        self,
        field_name: str,
        block: str,
        storage_length: int | None,
    ) -> bool:
        upper_name = field_name.upper()
        upper_block = block.upper()

        if "-YEAR-" in upper_name or " YEAR " in upper_name:
            return False

        if "-MONTH-" in upper_name or " MONTH " in upper_name:
            return False

        if "-DAY-" in upper_name or " DAY " in upper_name:
            return False

        if not (
            upper_name.endswith("DATE")
            or "-DATE-" in upper_name
            or upper_name.endswith(" DATE")
            or " DATE " in upper_name
            or " DATE_" in upper_name
        ):
            return False

        if storage_length == 8:
            return True

        if (
            "YEAR" in upper_block
            and "MONTH" in upper_block
            and "DAY" in upper_block
        ):
            return True

        return False

    def parse_block(
        self,
        block: str,
        usage: str,
        storage_length: int | None,
    ) -> tuple[str | None, int | None, int | None, str | None]:
        upper = self.clean_text(
            value=block,
        ).upper()

        decimal_match = self.DECIMAL_PAREN.search(
            upper,
        )

        if decimal_match:
            int_digits = int(
                decimal_match.group("int_digits"),
            )

            dec_digits = int(
                decimal_match.group("dec_digits"),
            )

            precision = int_digits + dec_digits

            return (
                "DECIMAL",
                precision,
                dec_digits,
                self.clean_picture(
                    decimal_match.group(0),
                ),
            )

        decimal_match = self.DECIMAL_INLINE.search(
            upper,
        )

        if decimal_match:
            integer_digits = len(
                decimal_match.group("int_part").replace(
                    "S",
                    "",
                )
            )

            decimal_digits = len(
                decimal_match.group("dec_part"),
            )

            precision = integer_digits + decimal_digits

            return (
                "DECIMAL",
                precision,
                decimal_digits,
                self.clean_picture(
                    decimal_match.group(0),
                ),
            )

        signed_fraction_match = self.SIGNED_FRACTION.search(
            upper,
        )

        if signed_fraction_match:
            decimal_digits = len(
                signed_fraction_match.group("dec_part"),
            )

            return (
                "DECIMAL",
                decimal_digits,
                decimal_digits,
                self.clean_picture(
                    signed_fraction_match.group(0),
                ),
            )

        x_paren = self.X_PAREN.search(
            upper,
        )

        if x_paren:
            length = int(
                x_paren.group("length"),
            )

            if length == 1:
                return (
                    "CHAR",
                    1,
                    None,
                    "X",
                )

            return (
                "VARCHAR",
                length,
                None,
                "X",
            )

        nine_paren = self.NINE_PAREN.search(
            upper,
        )

        if nine_paren:
            digits = int(
                nine_paren.group("digits"),
            )

            if usage in {"COMP", "COMP-3"}:
                return (
                    "DECIMAL",
                    self.comp3_precision_from_storage(
                        storage_length=storage_length,
                    )
                    if usage == "COMP-3"
                    else digits,
                    0,
                    "9",
                )

            datatype = self.integer_datatype_for_digits(
                digits=digits,
            )

            return (
                datatype,
                None,
                None,
                "9",
            )

        inline_x = self.INLINE_X.search(
            upper,
        )

        if inline_x:
            raw = self.clean_picture(
                inline_x.group(0),
            )

            length = len(raw)

            if length == 1 and storage_length and storage_length > 1:
                return (
                    "VARCHAR",
                    storage_length,
                    None,
                    "X",
                )

            if length == 1:
                return (
                    "CHAR",
                    1,
                    None,
                    "X",
                )

            return (
                "VARCHAR",
                length,
                None,
                "X",
            )

        inline_9 = self.INLINE_9.search(
            upper,
        )

        if inline_9:
            raw = self.clean_picture(
                inline_9.group(0),
            )

            digits = len(
                raw.replace(
                    "S",
                    "",
                )
            )

            if usage in {"COMP", "COMP-3"}:
                return (
                    "DECIMAL",
                    self.comp3_precision_from_storage(
                        storage_length=storage_length,
                    )
                    if usage == "COMP-3"
                    else digits,
                    0,
                    "9",
                )

            datatype = self.integer_datatype_for_digits(
                digits=digits,
            )

            return (
                datatype,
                None,
                None,
                "9",
            )

        if storage_length:
            return (
                "VARCHAR",
                storage_length,
                None,
                None,
            )

        return (
            None,
            None,
            None,
            None,
        )

    def clean_text(
        self,
        value: str,
    ) -> str:
        if value is None:
            return ""

        cleaned = str(value)

        cleaned = cleaned.replace(
            "\t",
            " ",
        )

        cleaned = cleaned.replace(
            "\u00a0",
            " ",
        )

        cleaned = re.sub(
            r"<[^>]+>",
            " ",
            cleaned,
        )

        cleaned = re.sub(
            r"\s+",
            " ",
            cleaned,
        ).strip()

        return cleaned

    def clean_picture(
        self,
        value: str,
    ) -> str:
        if value is None:
            return ""

        cleaned = str(value).upper()

        cleaned = re.sub(
            r"\s+",
            "",
            cleaned,
        )

        cleaned = cleaned.replace(
            "PICTURE",
            "",
        )

        cleaned = cleaned.replace(
            "PIC",
            "",
        )

        return cleaned.strip()

    def integer_datatype_for_digits(
        self,
        digits: int,
    ) -> str:
        if digits <= 4:
            return "SMALLINT"

        if digits <= 9:
            return "INTEGER"

        return "BIGINT"

    def comp3_precision_from_storage(
        self,
        storage_length: int | None,
    ) -> int:
        if storage_length:
            return max(
                storage_length * 2 - 1,
                1,
            )

        return 9

    def derive_basetype(
        self,
        datatype: str | None,
    ) -> str | None:
        if not datatype:
            return None

        upper = datatype.upper()

        if upper in {"CHAR", "VARCHAR"}:
            return "TEXT"

        if upper in {"SMALLINT", "INTEGER", "BIGINT", "DECIMAL"}:
            return "NUMERIC"

        if upper in {"DATE", "TIMESTAMP", "DATETIME"}:
            return "DATE"

        return None