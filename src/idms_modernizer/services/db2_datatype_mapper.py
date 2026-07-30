import re

print("LOADED DB2DatatypeMapper VERSION DEBUG-PIC-PARENS-V-COMP3-FIX-2026-07-30-2")


class DB2DatatypeMapper:
    DEFAULT_CHAR_LENGTH = 1
    DEFAULT_DECIMAL_PRECISION = 18
    DEFAULT_DECIMAL_SCALE = 0
    DEBUG = True

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

        picture = str(picture or "").strip()

        length = (
            getattr(field, "length", None)
            or getattr(field, "precision", None)
            or getattr(field, "storage_length", None)
            or getattr(field, "physical_length", None)
            or getattr(field, "byte_length", None)
        )

        scale = getattr(field, "scale", None)

        if DB2DatatypeMapper.DEBUG:
            print(
                "DB2_MAP_DEBUG_INPUT",
                f"datatype={datatype}",
                f"picture={repr(picture)}",
                f"length={length}",
                f"scale={scale}",
            )

        if datatype == "DATE":
            return "DATE"

        if datatype in {"TIMESTAMP", "DATETIME"}:
            return "TIMESTAMP"

        if picture:
            result = DB2DatatypeMapper.map_picture(
                picture=picture,
                fallback_length=length,
                fallback_scale=scale,
            )

            if DB2DatatypeMapper.DEBUG:
                print(
                    "DB2_MAP_DEBUG_RESULT",
                    f"picture={repr(picture)}",
                    f"result={result}",
                )

            return result

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
        return DB2DatatypeMapper.map(
            field=field,
        )

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

        clean_upper = clean.upper()

        has_comp3 = "COMP-3" in clean_upper
        has_comp = bool(re.search(r"\bCOMP\b", clean_upper)) and not has_comp3

        core = DB2DatatypeMapper.picture_core(
            picture=clean,
        )

        if DB2DatatypeMapper.DEBUG:
            print(
                "DB2_MAP_PICTURE_DEBUG_INPUT",
                f"picture={repr(picture)}",
                f"clean={repr(clean)}",
                f"core={repr(core)}",
                f"has_comp3={has_comp3}",
                f"has_comp={has_comp}",
                f"fallback_length={fallback_length}",
                f"fallback_scale={fallback_scale}",
            )

        if DB2DatatypeMapper.picture_is_char(core):
            length = DB2DatatypeMapper.char_length(
                picture=core,
                fallback_length=fallback_length,
            )

            result = f"CHAR({length})"

            if DB2DatatypeMapper.DEBUG:
                print(
                    "DB2_MAP_PICTURE_DEBUG_RESULT",
                    f"core={repr(core)}",
                    f"result={result}",
                )

            return result

        if DB2DatatypeMapper.picture_is_decimal(core):
            precision, scale = DB2DatatypeMapper.decimal_precision_scale(
                picture=core,
            )

            result = DB2DatatypeMapper.format_decimal(
                precision=precision,
                scale=scale,
                force_scale=True,
            )

            if DB2DatatypeMapper.DEBUG:
                print(
                    "DB2_MAP_PICTURE_DEBUG_RESULT",
                    f"core={repr(core)}",
                    f"precision={precision}",
                    f"scale={scale}",
                    f"result={result}",
                )

            return result

        if DB2DatatypeMapper.picture_is_numeric(core):
            precision = DB2DatatypeMapper.numeric_precision(
                picture=core,
                fallback_length=fallback_length,
            )

            if has_comp3 or has_comp:
                result = DB2DatatypeMapper.format_decimal(
                    precision=precision,
                    scale=0,
                    force_scale=True,
                )
            else:
                result = DB2DatatypeMapper.format_decimal(
                    precision=precision,
                    scale=0,
                    force_scale=False,
                )

            if DB2DatatypeMapper.DEBUG:
                print(
                    "DB2_MAP_PICTURE_DEBUG_RESULT",
                    f"core={repr(core)}",
                    f"precision={precision}",
                    "scale=0",
                    f"result={result}",
                )

            return result

        precision = DB2DatatypeMapper.safe_int(
            value=fallback_length,
            default=DB2DatatypeMapper.DEFAULT_DECIMAL_PRECISION,
        )

        scale = DB2DatatypeMapper.safe_int(
            value=fallback_scale,
            default=DB2DatatypeMapper.DEFAULT_DECIMAL_SCALE,
        )

        if has_comp3 or has_comp:
            result = DB2DatatypeMapper.format_decimal(
                precision=precision,
                scale=scale,
                force_scale=True,
            )
        else:
            result = f"CHAR({DB2DatatypeMapper.DEFAULT_CHAR_LENGTH})"

        if DB2DatatypeMapper.DEBUG:
            print(
                "DB2_MAP_PICTURE_DEBUG_FALLBACK",
                f"picture={repr(picture)}",
                f"core={repr(core)}",
                f"result={result}",
            )

        return result

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
        picture: str,
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

        if re.fullmatch(r"X[(][0-9]+[)]", text):
            return True

        if re.fullmatch(r"X+", text):
            return True

        return False

    @staticmethod
    def picture_is_numeric(
        picture: str,
    ) -> bool:
        text = str(picture or "").upper()

        if re.fullmatch(r"S?9[(][0-9]+[)]", text):
            return True

        if re.fullmatch(r"S?9+", text):
            return True

        return False

    @staticmethod
    def picture_is_decimal(
        picture: str,
    ) -> bool:
        text = str(picture or "").upper()

        if "V" not in text:
            return False

        if re.fullmatch(r"S?9[(][0-9]+[)]V9[(][0-9]+[)]", text):
            return True

        if re.fullmatch(r"S?9[(][0-9]+[)]V9+", text):
            return True

        if re.fullmatch(r"S?9+V9[(][0-9]+[)]", text):
            return True

        if re.fullmatch(r"S?9+V9+", text):
            return True

        return False

    @staticmethod
    def char_length(
        picture: str,
        fallback_length=None,
    ) -> int:
        text = str(picture or "").upper()

        match = re.fullmatch(r"X[(]([0-9]+)[)]", text)

        if match:
            return int(match.group(1))

        if re.fullmatch(r"X+", text):
            return len(text)

        return DB2DatatypeMapper.safe_int(
            value=fallback_length,
            default=DB2DatatypeMapper.DEFAULT_CHAR_LENGTH,
        )

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

        match = re.fullmatch(r"9[(]([0-9]+)[)]", text)

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
                    number_text = text[index + 2:close_index].strip()

                    if number_text.isdigit():
                        total += int(number_text)
                        index = close_index + 1
                        continue

            total += 1
            index += 1

        return total

    @staticmethod
    def count_9_digits(
        value: str,
    ) -> int:
        return DB2DatatypeMapper.count_numeric_digits(
            value=value,
        )

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