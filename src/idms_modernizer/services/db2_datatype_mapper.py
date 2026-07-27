import re


class DB2DatatypeMapper:
    """
    Maps enriched field datatypes to DB2 datatypes.

    Generic behavior only:
    - No business field-name rules.
    - Mapping is based only on datatype, length, scale, and PIC metadata.
    """

    DEFAULT_VARCHAR_LENGTH = 255
    DEFAULT_DECIMAL_PRECISION = 18
    DEFAULT_DECIMAL_SCALE = 0

    @staticmethod
    def map(
        field,
    ) -> str:
        datatype = (
            getattr(field, "datatype", None)
            or "VARCHAR"
        ).upper()

        length = DB2DatatypeMapper.best_length(
            field=field,
        )

        scale = getattr(
            field,
            "scale",
            None,
        )

        picture = (
            getattr(field, "picture", None)
            or ""
        ).upper()

        if datatype == "DATE":
            return "DATE"

        if datatype in {
            "TIMESTAMP",
            "DATETIME",
        }:
            return "TIMESTAMP"

        if datatype in {
            "SMALLINT",
            "INTEGER",
            "INT",
            "BIGINT",
            "COMP",
        }:
            return "INTEGER"

        if datatype in {
            "DECIMAL",
            "NUMERIC",
            "COMP-3",
        }:
            return DB2DatatypeMapper.map_decimal(
                length=length,
                scale=scale,
            )

        if datatype in {
            "DISPLAY",
            "CHAR",
            "VARCHAR",
        }:
            if DB2DatatypeMapper.picture_is_decimal(
                picture=picture,
            ):
                precision, decimal_scale = DB2DatatypeMapper.decimal_from_picture(
                    picture=picture,
                )

                return DB2DatatypeMapper.map_decimal(
                    length=precision,
                    scale=decimal_scale,
                )

            if DB2DatatypeMapper.picture_is_numeric(
                picture=picture,
            ):
                return "INTEGER"

            return DB2DatatypeMapper.map_character(
                length=length,
            )

        return DB2DatatypeMapper.map_character(
            length=length,
        )

    @staticmethod
    def best_length(
        field,
    ) -> int | None:
        length = getattr(
            field,
            "length",
            None,
        )

        picture = (
            getattr(field, "picture", None)
            or ""
        ).upper()

        picture_length = DB2DatatypeMapper.length_from_picture(
            picture=picture,
        )

        occurs_max = getattr(
            field,
            "occurs_max",
            None,
        )

        start_position = getattr(
            field,
            "start_position",
            None,
        )

        end_position = getattr(
            field,
            "end_position",
            None,
        )

        physical_length = None

        if start_position is not None and end_position is not None:
            try:
                physical_length = int(end_position) - int(start_position) + 1
            except Exception:
                physical_length = None

        numeric_length = None

        if length is not None:
            try:
                numeric_length = int(length)
            except Exception:
                numeric_length = None

        expanded_length = None

        if occurs_max and numeric_length:
            try:
                expanded_length = int(occurs_max) * int(numeric_length)
            except Exception:
                expanded_length = None

        candidates = [
            value
            for value in [
                physical_length,
                expanded_length,
                picture_length,
                numeric_length,
            ]
            if value is not None and value > 0
        ]

        if not candidates:
            return None

        return max(candidates)

    @staticmethod
    def map_character(
        length,
    ) -> str:
        actual_length = DB2DatatypeMapper.safe_int(
            value=length,
            default=DB2DatatypeMapper.DEFAULT_VARCHAR_LENGTH,
        )

        if actual_length <= 1:
            return "CHAR(1)"

        return f"VARCHAR({actual_length})"

    @staticmethod
    def map_decimal(
        length,
        scale,
    ) -> str:
        precision = DB2DatatypeMapper.safe_int(
            value=length,
            default=DB2DatatypeMapper.DEFAULT_DECIMAL_PRECISION,
        )

        actual_scale = DB2DatatypeMapper.safe_int(
            value=scale,
            default=DB2DatatypeMapper.DEFAULT_DECIMAL_SCALE,
        )

        if precision < 1:
            precision = DB2DatatypeMapper.DEFAULT_DECIMAL_PRECISION

        if actual_scale < 0:
            actual_scale = DB2DatatypeMapper.DEFAULT_DECIMAL_SCALE

        if actual_scale > precision:
            actual_scale = 0

        return f"DECIMAL({precision},{actual_scale})"

    @staticmethod
    def picture_is_numeric(
        picture: str,
    ) -> bool:
        return "9" in picture and "V" not in picture

    @staticmethod
    def picture_is_decimal(
        picture: str,
    ) -> bool:
        return "9" in picture and "V" in picture

    @staticmethod
    def length_from_picture(
        picture: str,
    ) -> int | None:
        if not picture:
            return None

        picture = picture.upper().replace(" ", "")

        char_match = re.search(
            r"X$(\d+)$",
            picture,
        )

        if char_match:
            return int(
                char_match.group(1),
            )

        if picture == "X":
            return 1

        digit_match = re.search(
            r"9$(\d+)$",
            picture,
        )

        if digit_match:
            return int(
                digit_match.group(1),
            )

        if picture in {"9", "S9"}:
            return 1

        return None

    @staticmethod
    def decimal_from_picture(
        picture: str,
    ) -> tuple[int, int]:
        picture = picture.upper().replace("S", "").replace(" ", "")

        if "V" not in picture:
            precision = DB2DatatypeMapper.length_from_picture(
                picture=picture,
            ) or 1

            return precision, 0

        before, after = picture.split("V", 1)

        before_digits = DB2DatatypeMapper.count_9_digits(
            value=before,
        )

        after_digits = DB2DatatypeMapper.count_9_digits(
            value=after,
        )

        return before_digits + after_digits, after_digits

    @staticmethod
    def count_9_digits(
        value: str,
    ) -> int:
        total = 0

        for match in re.finditer(
            r"9(?:$(\d+)$)?",
            value,
        ):
            if match.group(1):
                total += int(
                    match.group(1),
                )
            else:
                total += 1

        return total

    @staticmethod
    def safe_int(
        value,
        default: int,
    ) -> int:
        if value is None:
            return default

        try:
            return int(value)

        except Exception:
            return default