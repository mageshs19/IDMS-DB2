import re


class DB2DatatypeMapper:
    """
    Generic DB2 datatype mapper for Schema Listing conversion.

    Rules:
    - Sheet Mapping and DB2 model must use the same datatype logic.
    - Numeric COBOL PIC always maps to DECIMAL.
    - Do not emit SMALLINT, INTEGER, or BIGINT from Schema Listing fields.
    - Character PIC maps to CHAR / VARCHAR based on length.
    - DATE and TIMESTAMP are preserved.
    """

    DEFAULT_CHAR_LENGTH = 1
    DEFAULT_DECIMAL_PRECISION = 18
    DEFAULT_DECIMAL_SCALE = 0
    DEBUG = False

    @staticmethod
    def map(
        field,
    ) -> str:
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

        picture = str(picture or "").strip()

        length = DB2DatatypeMapper.first_present(
            getattr(field, "length", None),
            getattr(field, "precision", None),
            getattr(field, "logical_length", None),
            getattr(field, "storage_length", None),
            getattr(field, "physical_length", None),
            getattr(field, "byte_length", None),
            getattr(field, "bytes", None),
        )

        scale = getattr(field, "scale", None)

        if datatype == "DATE":
            return "DATE"

        if datatype in {"TIMESTAMP", "DATETIME"}:
            return "TIMESTAMP"

        if datatype == "TIME":
            return "TIME"

        if picture:
            return DB2DatatypeMapper.map_picture(
                picture=picture,
                fallback_length=length,
                fallback_scale=scale,
                fallback_datatype=datatype,
            )

        return DB2DatatypeMapper.map_without_picture(
            fallback_datatype=datatype,
            fallback_length=length,
            fallback_scale=scale,
        )

    @staticmethod
    def map_datatype(
        field,
    ) -> str:
        return DB2DatatypeMapper.map(
            field=field,
        )

    @staticmethod
    def map_picture(
        picture: str,
        fallback_length=None,
        fallback_scale=None,
        fallback_datatype: str = "",
    ) -> str:
        clean = DB2DatatypeMapper.clean_picture(
            picture=picture,
        )

        if not clean:
            return DB2DatatypeMapper.map_without_picture(
                fallback_datatype=fallback_datatype,
                fallback_length=fallback_length,
                fallback_scale=fallback_scale,
            )

        core = DB2DatatypeMapper.picture_core(
            picture=clean,
        )

        if DB2DatatypeMapper.picture_is_char(core):
            length = DB2DatatypeMapper.char_length(
                picture=core,
                fallback_length=fallback_length,
            )

            if length <= 1:
                return "CHAR(1)"

            return f"VARCHAR({length})"

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

            return DB2DatatypeMapper.format_decimal(
                precision=precision,
                scale=0,
                force_scale=False,
            )

        return DB2DatatypeMapper.map_without_picture(
            fallback_datatype=fallback_datatype,
            fallback_length=fallback_length,
            fallback_scale=fallback_scale,
        )

    @staticmethod
    def map_without_picture(
        fallback_datatype: str,
        fallback_length=None,
        fallback_scale=None,
    ) -> str:
        datatype = str(fallback_datatype or "").strip().upper()

        if datatype == "DATE":
            return "DATE"

        if datatype in {"TIMESTAMP", "DATETIME"}:
            return "TIMESTAMP"

        if datatype == "TIME":
            return "TIME"

        if datatype == "SMALLINT":
            return "DECIMAL(4)"

        if datatype in {"INTEGER", "INT"}:
            return "DECIMAL(9)"

        if datatype == "BIGINT":
            return "DECIMAL(18)"

        if datatype in {"DECIMAL", "NUMERIC", "COMP", "COMP-3"}:
            precision = DB2DatatypeMapper.safe_int(
                value=fallback_length,
                default=DB2DatatypeMapper.DEFAULT_DECIMAL_PRECISION,
            )

            scale = DB2DatatypeMapper.safe_int(
                value=fallback_scale,
                default=DB2DatatypeMapper.DEFAULT_DECIMAL_SCALE,
            )

            return DB2DatatypeMapper.format_decimal(
                precision=precision,
                scale=scale,
                force_scale=scale > 0,
            )

        if datatype == "CHAR":
            length = DB2DatatypeMapper.safe_int(
                value=fallback_length,
                default=DB2DatatypeMapper.DEFAULT_CHAR_LENGTH,
            )

            return f"CHAR({length})"

        if datatype in {"VARCHAR", "DISPLAY", "TEXT", "ALPHANUMERIC"}:
            length = DB2DatatypeMapper.safe_int(
                value=fallback_length,
                default=DB2DatatypeMapper.DEFAULT_CHAR_LENGTH,
            )

            if length <= 1:
                return "CHAR(1)"

            return f"VARCHAR({length})"

        length = DB2DatatypeMapper.safe_int(
            value=fallback_length,
            default=DB2DatatypeMapper.DEFAULT_CHAR_LENGTH,
        )

        if length <= 1:
            return "CHAR(1)"

        return f"VARCHAR({length})"

    @staticmethod
    def clean_picture(
        picture: str,
    ) -> str:
        text = str(picture or "").strip()
        text = text.replace("\u00a0", " ")
        text = text.replace(".", "")
        text = re.sub(r"\s+", " ", text)

        return text.strip()

    @staticmethod
    def picture_core(
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

    @staticmethod
    def picture_is_char(
        picture: str,
    ) -> bool:
        text = str(picture or "").upper()

        if text.startswith("X(") and text.endswith(")"):
            return DB2DatatypeMapper.extract_parenthesized_int(text) is not None

        return bool(text) and set(text) == {"X"}

    @staticmethod
    def char_length(
        picture: str,
        fallback_length=None,
    ) -> int:
        text = str(picture or "").upper()

        if text.startswith("X(") and text.endswith(")"):
            parsed = DB2DatatypeMapper.extract_parenthesized_int(text)

            if parsed is not None:
                return parsed

        if re.fullmatch(r"X+", text):
            return len(text)

        return DB2DatatypeMapper.safe_int(
            value=fallback_length,
            default=DB2DatatypeMapper.DEFAULT_CHAR_LENGTH,
        )

    @staticmethod
    def picture_is_numeric(
        picture: str,
    ) -> bool:
        text = str(picture or "").upper()

        if text.startswith("S"):
            text = text[1:]

        return "9" in text and "V" not in text

    @staticmethod
    def picture_is_decimal(
        picture: str,
    ) -> bool:
        text = str(picture or "").upper()

        if text.startswith("S"):
            text = text[1:]

        return "9" in text and "V" in text

    @staticmethod
    def numeric_precision(
        picture: str,
        fallback_length=None,
    ) -> int:
        text = str(picture or "").upper()

        if text.startswith("S"):
            text = text[1:]

        if "V" in text:
            precision, _scale = DB2DatatypeMapper.decimal_precision_scale(
                picture=picture,
            )

            return precision

        match = re.fullmatch(r"9$(\d+)$", text)

        if match:
            return int(match.group(1))

        if re.fullmatch(r"9+", text):
            return len(text)

        precision = DB2DatatypeMapper.count_numeric_digits(
            value=text,
        )

        if precision > 0:
            return precision

        return DB2DatatypeMapper.safe_int(
            value=fallback_length,
            default=DB2DatatypeMapper.DEFAULT_DECIMAL_PRECISION,
        )

    @staticmethod
    def decimal_precision_scale(
        picture: str,
    ) -> tuple[int, int]:
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

        integer_digits = DB2DatatypeMapper.count_numeric_digits(
            value=before_v,
        )

        decimal_digits = DB2DatatypeMapper.count_numeric_digits(
            value=after_v,
        )

        precision = integer_digits + decimal_digits
        scale = decimal_digits

        return precision, scale

    @staticmethod
    def count_numeric_digits(
        value: str,
    ) -> int:
        text = str(value or "").strip().upper()

        if text.startswith("S"):
            text = text[1:]

        total = 0
        index = 0

        while index < len(text):
            current_character = text[index]

            if current_character not in {"9", "0"}:
                index += 1
                continue

            if index + 1 < len(text) and text[index + 1] == "(":
                close_index = text.find(")", index + 2)

                if close_index != -1:
                    number_text = text[index + 2 : close_index].strip()

                    if number_text.isdigit():
                        total += int(number_text)
                        index = close_index + 1
                        continue

            total += 1
            index += 1

        return total

    @staticmethod
    def format_decimal(
        precision: int,
        scale: int,
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
    def extract_parenthesized_int(
        value: str,
    ) -> int | None:
        match = re.search(r"$(\d+)$", str(value or ""))

        if not match:
            return None

        return int(match.group(1))

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

    @staticmethod
    def first_present(
        *values,
    ):
        for value in values:
            if value is None:
                continue

            if isinstance(value, str) and not value.strip():
                continue

            return value

        return None