import re


class DB2DatatypeMapper:
    """
    Maps COBOL / IDMS PIC metadata to DB2 datatype.

    Rules:
    - PIC X(n) -> CHAR(n)
    - PIC X repeated -> CHAR(length)
    - PIC 9(n) -> DECIMAL(n)
    - PIC S9(n) -> DECIMAL(n)
    - PIC 9(n) COMP-3 -> DECIMAL(n,0)
    - PIC S9(n) COMP-3 -> DECIMAL(n,0)
    - PIC 9(n)V9(m) -> DECIMAL(n+m,m)
    - PIC S9(n)V9(m) -> DECIMAL(n+m,m)
    - PIC 9(n)V9(m) COMP-3 -> DECIMAL(n+m,m)
    - PIC S9(n)V9(m) COMP-3 -> DECIMAL(n+m,m)
    - DATE -> DATE
    - TIMESTAMP / DATETIME -> TIMESTAMP
    """

    DEFAULT_CHAR_LENGTH = 1
    DEFAULT_DECIMAL_PRECISION = 18
    DEFAULT_DECIMAL_SCALE = 0

    @staticmethod
    def map(field) -> str:
        datatype = (
            getattr(field, "datatype", None)
            or getattr(field, "data_type", None)
            or getattr(field, "type", None)
            or ""
        )
        datatype = str(datatype or "").strip().upper()

        picture = (
            getattr(field, "picture", None)
            or getattr(field, "pic", None)
            or getattr(field, "pic_clause", None)
            or ""
        )
        picture = str(picture or "").strip().upper()

        length = (
            getattr(field, "length", None)
            or getattr(field, "precision", None)
            or getattr(field, "storage_length", None)
            or getattr(field, "physical_length", None)
            or getattr(field, "byte_length", None)
        )

        scale = getattr(field, "scale", None)

        if datatype == "DATE":
            return "DATE"

        if datatype in {"TIMESTAMP", "DATETIME"}:
            return "TIMESTAMP"

        if picture:
            return DB2DatatypeMapper.map_picture(
                picture=picture,
                fallback_length=length,
                fallback_scale=scale,
            )

        if datatype in {"DECIMAL", "NUMERIC", "COMP", "COMP-3"}:
            precision = DB2DatatypeMapper.safe_int(
                value=length,
                default=DB2DatatypeMapper.DEFAULT_DECIMAL_PRECISION,
            )
            actual_scale = DB2DatatypeMapper.safe_int(
                value=scale,
                default=DB2DatatypeMapper.DEFAULT_DECIMAL_SCALE,
            )

            return DB2DatatypeMapper.format_decimal(
                precision=precision,
                scale=actual_scale,
                force_scale=actual_scale > 0,
            )

        if datatype in {"CHAR", "VARCHAR", "DISPLAY", "TEXT", "ALPHANUMERIC"}:
            actual_length = DB2DatatypeMapper.safe_int(
                value=length,
                default=DB2DatatypeMapper.DEFAULT_CHAR_LENGTH,
            )
            return f"CHAR({actual_length})"

        return f"CHAR({DB2DatatypeMapper.DEFAULT_CHAR_LENGTH})"

    @staticmethod
    def map_datatype(field) -> str:
        return DB2DatatypeMapper.map(field=field)

    @staticmethod
    def map_picture(
        picture: str,
        fallback_length=None,
        fallback_scale=None,
    ) -> str:
        clean = DB2DatatypeMapper.clean_picture(
            picture=picture,
        )

        if not clean:
            return f"CHAR({DB2DatatypeMapper.DEFAULT_CHAR_LENGTH})"

        has_comp3 = "COMP-3" in clean.upper()
        has_comp = bool(re.search(r"\bCOMP\b", clean.upper())) and not has_comp3

        core = DB2DatatypeMapper.picture_core(
            picture=clean,
        )

        if DB2DatatypeMapper.picture_is_char(core):
            length = DB2DatatypeMapper.char_length(
                picture=core,
                fallback_length=fallback_length,
            )
            return f"CHAR({length})"

        if DB2DatatypeMapper.picture_is_decimal(core):
            precision, scale = DB2DatatypeMapper.decimal_precision_scale(
                picture=core,
            )
            return DB2DatatypeMapper.format_decimal(
                precision=precision,
                scale=scale,
                force_scale=True,
            )

        if DB2DatatypeMapper.picture_is_numeric(core):
            precision = DB2DatatypeMapper.numeric_precision(
                picture=core,
                fallback_length=fallback_length,
            )

            if has_comp3 or has_comp:
                return DB2DatatypeMapper.format_decimal(
                    precision=precision,
                    scale=0,
                    force_scale=True,
                )

            return DB2DatatypeMapper.format_decimal(
                precision=precision,
                scale=0,
                force_scale=False,
            )

        if fallback_length:
            actual_length = DB2DatatypeMapper.safe_int(
                value=fallback_length,
                default=DB2DatatypeMapper.DEFAULT_CHAR_LENGTH,
            )
            return f"CHAR({actual_length})"

        return f"CHAR({DB2DatatypeMapper.DEFAULT_CHAR_LENGTH})"

    @staticmethod
    def clean_picture(picture: str) -> str:
        value = str(picture or "").strip().upper()

        value = value.replace("PICTURE", "")
        value = value.replace("PIC", "")
        value = value.replace(".", "")
        value = value.replace("\u00a0", " ")
        value = value.replace("\t", " ")

        value = re.sub(r"\s+", " ", value).strip()

        value = value.replace(" (", "(")
        value = value.replace("( ", "(")
        value = value.replace(" )", ")")
        value = value.replace(") ", ") ")

        value = re.sub(r"\s+", " ", value).strip()

        return value

    @staticmethod
    def picture_core(picture: str) -> str:
        value = str(picture or "").strip().upper()

        value = value.replace("COMP-3", "")
        value = re.sub(r"\bCOMP\b", "", value)
        value = value.replace("DISPLAY", "")
        value = value.replace("USAGE", "")
        value = value.replace("IS", "")
        value = value.replace("SIGN", "")
        value = value.replace("LEADING", "")
        value = value.replace("TRAILING", "")
        value = value.replace("SEPARATE", "")
        value = value.replace("CHARACTER", "")

        value = re.sub(r"\s+", "", value).strip()

        return value

    @staticmethod
    def picture_is_char(picture: str) -> bool:
        value = str(picture or "").strip().upper()

        if value.startswith("X(") and value.endswith(")"):
            return DB2DatatypeMapper.extract_parenthesized_int(value) is not None

        if value and set(value) == {"X"}:
            return True

        return False

    @staticmethod
    def picture_is_numeric(picture: str) -> bool:
        value = str(picture or "").strip().upper()

        if value.startswith("S"):
            value = value[1:]

        if "V" in value:
            return False

        if value.startswith("9(") and value.endswith(")"):
            return DB2DatatypeMapper.extract_parenthesized_int(value) is not None

        if value and set(value) == {"9"}:
            return True

        return False

    @staticmethod
    def picture_is_decimal(picture: str) -> bool:
        value = str(picture or "").strip().upper()

        if value.startswith("S"):
            value = value[1:]

        return "V" in value and "9" in value

    @staticmethod
    def char_length(
        picture: str,
        fallback_length=None,
    ) -> int:
        value = str(picture or "").strip().upper()

        if value.startswith("X(") and value.endswith(")"):
            parsed_length = DB2DatatypeMapper.extract_parenthesized_int(value)

            if parsed_length is not None:
                return parsed_length

        if value and set(value) == {"X"}:
            return len(value)

        return DB2DatatypeMapper.safe_int(
            value=fallback_length,
            default=DB2DatatypeMapper.DEFAULT_CHAR_LENGTH,
        )

    @staticmethod
    def numeric_precision(
        picture: str,
        fallback_length=None,
    ) -> int:
        value = str(picture or "").strip().upper()

        if value.startswith("S"):
            value = value[1:]

        if "V" in value:
            precision, _scale = DB2DatatypeMapper.decimal_precision_scale(
                picture=picture,
            )
            return precision

        if value.startswith("9(") and value.endswith(")"):
            parsed_precision = DB2DatatypeMapper.extract_parenthesized_int(value)

            if parsed_precision is not None:
                return parsed_precision

        if value and set(value) == {"9"}:
            return len(value)

        return DB2DatatypeMapper.safe_int(
            value=fallback_length,
            default=DB2DatatypeMapper.DEFAULT_DECIMAL_PRECISION,
        )

    @staticmethod
    def decimal_precision_scale(picture: str) -> tuple[int, int]:
        value = str(picture or "").strip().upper()

        if value.startswith("S"):
            value = value[1:]

        if "V" not in value:
            precision = DB2DatatypeMapper.numeric_precision(
                picture=value,
                fallback_length=DB2DatatypeMapper.DEFAULT_DECIMAL_PRECISION,
            )
            return precision, 0

        before_v, after_v = value.split("V", 1)

        integer_digits = DB2DatatypeMapper.count_9_digits(
            value=before_v,
        )
        decimal_digits = DB2DatatypeMapper.count_9_digits(
            value=after_v,
        )

        return integer_digits + decimal_digits, decimal_digits

    @staticmethod
    def count_9_digits(value: str) -> int:
        text = str(value or "").strip().upper()

        if text.startswith("S"):
            text = text[1:]

        total = 0
        index = 0

        while index < len(text):
            char = text[index]

            if char != "9":
                index += 1
                continue

            if index + 1 < len(text) and text[index + 1] == "(":
                close_index = text.find(")", index + 2)

                if close_index != -1:
                    number_text = text[index + 2:close_index].strip()

                    if number_text.isdigit():
                        total += int(number_text)
                        index = close_index + 1
                        continue

            total += 1
            index += 1

        return total

    @staticmethod
    def extract_parenthesized_int(value: str) -> int | None:
        text = str(value or "").strip()

        open_index = text.find("(")
        close_index = text.find(")", open_index + 1)

        if open_index == -1 or close_index == -1:
            return None

        number_text = text[open_index + 1:close_index].strip()

        if not number_text.isdigit():
            return None

        return int(number_text)

    @staticmethod
    def format_decimal(
        precision: int,
        scale: int = 0,
        force_scale: bool = False,
    ) -> str:
        actual_precision = DB2DatatypeMapper.safe_int(
            value=precision,
            default=DB2DatatypeMapper.DEFAULT_DECIMAL_PRECISION,
        )
        actual_scale = DB2DatatypeMapper.safe_int(
            value=scale,
            default=DB2DatatypeMapper.DEFAULT_DECIMAL_SCALE,
        )

        if force_scale or actual_scale > 0:
            return f"DECIMAL({actual_precision},{actual_scale})"

        return f"DECIMAL({actual_precision})"

    @staticmethod
    def safe_int(
        value,
        default: int,
    ) -> int:
        try:
            if value is None:
                return default

            text = str(value).strip()

            if not text:
                return default

            return int(text)
        except Exception:
            return default