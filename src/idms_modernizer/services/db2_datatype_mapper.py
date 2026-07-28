import re


class DB2DatatypeMapper:
    DEFAULT_CHARACTER_LENGTH = 1
    DEFAULT_DECIMAL_PRECISION = 18
    DEFAULT_DECIMAL_SCALE = 0

    @staticmethod
    def map(field) -> str:
        datatype = (
            getattr(field, "datatype", None)
            or getattr(field, "data_type", None)
            or getattr(field, "type", None)
            or "CHAR"
        )
        datatype = str(datatype).strip().upper()

        length = DB2DatatypeMapper.best_length(field=field)

        scale = getattr(field, "scale", None)

        picture = (
            getattr(field, "picture", None)
            or getattr(field, "pic", None)
            or getattr(field, "pic_clause", None)
            or ""
        )
        picture = str(picture).strip().upper()

        if datatype == "DATE":
            return "DATE"

        if datatype in {"TIMESTAMP", "DATETIME"}:
            return "TIMESTAMP"

        if DB2DatatypeMapper.picture_is_decimal(picture=picture):
            precision, decimal_scale = DB2DatatypeMapper.decimal_from_picture(
                picture=picture,
            )
            return DB2DatatypeMapper.map_decimal(
                length=precision,
                scale=decimal_scale,
            )

        if DB2DatatypeMapper.picture_is_numeric(picture=picture):
            precision = DB2DatatypeMapper.numeric_precision_from_picture(
                picture=picture,
            )
            return DB2DatatypeMapper.map_decimal(
                length=precision,
                scale=0,
            )

        if datatype in {
            "DECIMAL",
            "NUMERIC",
            "COMP",
            "COMP-3",
            "PACKED",
            "PACKED-DECIMAL",
        }:
            return DB2DatatypeMapper.map_decimal(
                length=length,
                scale=scale,
            )

        return DB2DatatypeMapper.map_character(
            length=length,
        )

    @staticmethod
    def map_datatype(field) -> str:
        return DB2DatatypeMapper.map(field=field)

    @staticmethod
    def map_character(length) -> str:
        actual_length = DB2DatatypeMapper.safe_int(
            value=length,
            default=DB2DatatypeMapper.DEFAULT_CHARACTER_LENGTH,
        )

        if actual_length <= 0:
            actual_length = DB2DatatypeMapper.DEFAULT_CHARACTER_LENGTH

        if actual_length == 100:
            return "VARCHAR(100)"

        return f"CHAR({actual_length})"

    @staticmethod
    def map_decimal(length, scale) -> str:
        precision = DB2DatatypeMapper.safe_int(
            value=length,
            default=DB2DatatypeMapper.DEFAULT_DECIMAL_PRECISION,
        )

        decimal_scale = DB2DatatypeMapper.safe_int(
            value=scale,
            default=DB2DatatypeMapper.DEFAULT_DECIMAL_SCALE,
        )

        if precision <= 0:
            precision = DB2DatatypeMapper.DEFAULT_DECIMAL_PRECISION

        if decimal_scale < 0:
            decimal_scale = DB2DatatypeMapper.DEFAULT_DECIMAL_SCALE

        if decimal_scale > 0:
            return f"DECIMAL({precision},{decimal_scale})"

        return f"DECIMAL({precision})"

    @staticmethod
    def best_length(field) -> int | None:
        length = getattr(field, "length", None)
        storage_length = getattr(field, "storage_length", None)
        physical_length = getattr(field, "physical_length", None)
        effective_length = getattr(field, "effective_length", None)

        picture = (
            getattr(field, "picture", None)
            or getattr(field, "pic", None)
            or getattr(field, "pic_clause", None)
            or ""
        )

        picture_length = DB2DatatypeMapper.length_from_picture(
            picture=picture,
        )

        occurs_max = getattr(field, "occurs_max", None)
        occurs_length = None

        if occurs_max is not None and picture_length is not None:
            occurs_max_int = DB2DatatypeMapper.safe_int(
                value=occurs_max,
                default=0,
            )
            if occurs_max_int > 0:
                occurs_length = picture_length * occurs_max_int

        candidates = [
            value
            for value in [
                effective_length,
                length,
                storage_length,
                physical_length,
                occurs_length,
                picture_length,
            ]
            if value is not None and DB2DatatypeMapper.safe_int(value, 0) > 0
        ]

        if not candidates:
            return None

        return max(DB2DatatypeMapper.safe_int(value, 0) for value in candidates)

    @staticmethod
    def length_from_picture(picture: str) -> int | None:
        value = DB2DatatypeMapper.normalize_picture(picture=picture)

        if not value:
            return None

        value = DB2DatatypeMapper.strip_picture_keywords(value=value)

        if "V" in value and "9" in value:
            precision, _ = DB2DatatypeMapper.decimal_from_picture(
                picture=value,
            )
            return precision

        if "9" in value:
            return DB2DatatypeMapper.numeric_precision_from_picture(
                picture=value,
            )

        repeated_x_match = re.search(
            r"X$(\d+)$",
            value,
            flags=re.IGNORECASE,
        )

        if repeated_x_match:
            return int(repeated_x_match.group(1))

        if "X" in value:
            return value.count("X")

        return None

    @staticmethod
    def picture_is_decimal(picture: str) -> bool:
        value = DB2DatatypeMapper.normalize_picture(picture=picture)
        value = DB2DatatypeMapper.strip_picture_keywords(value=value)
        return "V" in value and "9" in value

    @staticmethod
    def picture_is_numeric(picture: str) -> bool:
        value = DB2DatatypeMapper.normalize_picture(picture=picture)
        value = DB2DatatypeMapper.strip_picture_keywords(value=value)

        return bool(
            re.search(
                r"S?9",
                value,
                flags=re.IGNORECASE,
            )
        )

    @staticmethod
    def decimal_from_picture(picture: str) -> tuple[int, int]:
        value = DB2DatatypeMapper.normalize_picture(picture=picture)
        value = DB2DatatypeMapper.strip_picture_keywords(value=value)

        if "V" not in value:
            precision = DB2DatatypeMapper.numeric_precision_from_picture(
                picture=value,
            )
            return precision, 0

        integer_part, decimal_part = value.split("V", 1)

        integer_digits = DB2DatatypeMapper.count_9_digits(
            value=integer_part,
        )

        decimal_digits = DB2DatatypeMapper.count_9_digits(
            value=decimal_part,
        )

        return integer_digits + decimal_digits, decimal_digits

    @staticmethod
    def numeric_precision_from_picture(picture: str) -> int:
        value = DB2DatatypeMapper.normalize_picture(picture=picture)
        value = DB2DatatypeMapper.strip_picture_keywords(value=value)

        return DB2DatatypeMapper.count_9_digits(
            value=value,
        )

    @staticmethod
    def count_9_digits(value: str) -> int:
        if not value:
            return 0

        normalized = DB2DatatypeMapper.normalize_picture(
            picture=value,
        )

        total = 0

        repeated_matches = re.findall(
            r"9$(\d+)$",
            normalized,
            flags=re.IGNORECASE,
        )

        for repeated in repeated_matches:
            total += int(repeated)

        without_repeated = re.sub(
            r"9$\d+$",
            "",
            normalized,
            flags=re.IGNORECASE,
        )

        total += without_repeated.count("9")

        return total

    @staticmethod
    def normalize_picture(picture: str) -> str:
        value = str(picture or "").upper()
        value = value.replace(" ", "")
        value = value.replace(".", "")
        return value

    @staticmethod
    def strip_picture_keywords(value: str) -> str:
        cleaned = str(value or "").upper()

        for token in [
            "PICTURE",
            "PIC",
            "USAGE",
            "DISPLAY",
            "COMP-3",
            "COMP",
            "PACKED-DECIMAL",
            "PACKED",
            "IS",
        ]:
            cleaned = cleaned.replace(token, "")

        return cleaned.strip()

    @staticmethod
    def safe_int(value, default: int) -> int:
        try:
            if value is None:
                return default

            return int(value)
        except Exception:
            return default