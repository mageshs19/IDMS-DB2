import re

from idms_db2_converter.generators.naming import Naming
from idms_db2_converter.models import SchemaModel


class HostVariableGenerator:
    """
    Generates COBOL host variables for DB2 embedded SQL.

    Supports:
    - CHAR(n)
    - VARCHAR(n)
    - DECIMAL(p)
    - DECIMAL(p,s)
    - DATE
    - TIME
    - TIMESTAMP

    Schema Listing numeric rule:
    - Numeric fields come through as DECIMAL.
    - SMALLINT, INTEGER, BIGINT are normalized defensively to DECIMAL precision.
    """

    def generate(
        self,
        schema: SchemaModel,
        used_records: list[str],
    ) -> str:
        lines: list[str] = [
            "",
            "       EXEC SQL",
            "            INCLUDE SQLCA",
            "       END-EXEC.",
            "       EXEC SQL",
            "            BEGIN DECLARE SECTION",
            "       END-EXEC.",
            "",
        ]

        null_indicators: list[str] = []
        emitted_null_indicators: set[str] = set()

        physical_records = self.resolve_used_records(
            schema=schema,
            used_records=used_records,
        )

        for logical_record_name, physical_record_name in physical_records:
            if physical_record_name not in schema.records:
                continue

            record = schema.records[physical_record_name]

            logical_group_name = Naming.normalize(
                logical_record_name,
            )

            lines.append(
                f"     01 HV-{logical_group_name}."
            )

            for column_name, column in record.fields.items():
                host_variable = Naming.hv(
                    logical_record_name,
                    column_name,
                )

                datatype, length, scale = self.normalize_db2_datatype(
                    datatype=getattr(column, "datatype", None),
                    length=getattr(column, "length", None),
                    scale=getattr(column, "scale", None),
                )

                lines.extend(
                    self.column_to_cobol(
                        hv=host_variable,
                        datatype=datatype,
                        length=length,
                        scale=scale,
                    )
                )

                if getattr(column, "nullable", True):
                    null_indicator = Naming.ni(
                        logical_record_name,
                        column_name,
                    )

                    if null_indicator not in emitted_null_indicators:
                        emitted_null_indicators.add(
                            null_indicator,
                        )
                        null_indicators.append(
                            f"     01 {null_indicator:<45} PIC S9(4) COMP."
                        )

            lines.append("")

        if null_indicators:
            lines.extend(
                null_indicators,
            )

        lines.extend(
            [
                "       EXEC SQL",
                "            END DECLARE SECTION",
                "       END-EXEC.",
            ]
        )

        return "\n".join(lines)

    def resolve_used_records(
        self,
        schema: SchemaModel,
        used_records: list[str],
    ) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()

        for logical_record_name in used_records:
            if not logical_record_name:
                continue

            physical_record_name = self.physical_record_name(
                schema=schema,
                logical_record_name=logical_record_name,
            )

            key = (
                logical_record_name.upper(),
                physical_record_name.upper(),
            )

            if key in seen:
                continue

            seen.add(
                key,
            )

            result.append(
                (
                    logical_record_name.upper(),
                    physical_record_name,
                )
            )

        return result

    def physical_record_name(
        self,
        schema: SchemaModel,
        logical_record_name: str,
    ) -> str:
        logical_record_name = logical_record_name.upper()

        mapped = schema.record_table_map.get(
            logical_record_name,
        )

        if mapped and mapped in schema.records:
            return mapped

        normalized = logical_record_name.replace(
            "-",
            "_",
        )

        mapped = schema.record_table_map.get(
            normalized,
        )

        if mapped and mapped in schema.records:
            return mapped

        if logical_record_name in schema.records:
            return logical_record_name

        if normalized in schema.records:
            return normalized

        hyphen_name = logical_record_name.replace(
            "_",
            "-",
        )

        if hyphen_name in schema.records:
            return hyphen_name

        return logical_record_name

    def normalize_db2_datatype(
        self,
        datatype: str | None,
        length: int | None,
        scale: int | None,
    ) -> tuple[str, int | None, int | None]:
        value = str(datatype or "").strip().upper()

        if not value:
            return "CHAR", length, scale

        decimal_match = re.match(
            r"^(DECIMAL|NUMERIC|DEC)\s*$\s*(\d+)\s*(?:,\s*(\d+)\s*)?$$",
            value,
            flags=re.IGNORECASE,
        )

        if decimal_match:
            precision = int(decimal_match.group(2))
            parsed_scale = int(decimal_match.group(3) or 0)

            return "DECIMAL", precision, parsed_scale

        char_match = re.match(
            r"^(CHAR|CHARACTER)\s*$\s*(\d+)\s*$$",
            value,
            flags=re.IGNORECASE,
        )

        if char_match:
            return "CHAR", int(char_match.group(2)), scale

        varchar_match = re.match(
            r"^(VARCHAR|LONG VARCHAR)\s*$\s*(\d+)\s*$$",
            value,
            flags=re.IGNORECASE,
        )

        if varchar_match:
            return "VARCHAR", int(varchar_match.group(2)), scale

        if value in {"VARCHAR", "LONG VARCHAR"}:
            return "VARCHAR", self.safe_int(length, 255), scale

        if value in {"CHAR", "CHARACTER"}:
            return "CHAR", self.safe_int(length, 1), scale

        if value in {"DECIMAL", "NUMERIC", "DEC"}:
            return "DECIMAL", self.safe_int(length, 18), self.safe_int(scale, 0)

        if value == "SMALLINT":
            return "DECIMAL", 4, 0

        if value in {"INTEGER", "INT"}:
            return "DECIMAL", 9, 0

        if value == "BIGINT":
            return "DECIMAL", 18, 0

        if value == "DATE":
            return "DATE", None, None

        if value == "TIME":
            return "TIME", None, None

        if value == "TIMESTAMP":
            return "TIMESTAMP", None, None

        if value in {"DOUBLE", "FLOAT", "REAL"}:
            return value, None, None

        return value, length, scale

    def column_to_cobol(
        self,
        hv: str,
        datatype: str | None,
        length: int | None,
        scale: int | None,
    ) -> list[str]:
        datatype = (
            datatype
            or "CHAR"
        ).upper()

        if datatype in {
            "CHAR",
            "CHARACTER",
        }:
            actual_length = self.safe_int(
                length,
                1,
            )

            return [
                f"        05 {hv:<45} PIC X({actual_length})."
            ]

        if datatype in {
            "VARCHAR",
            "LONG VARCHAR",
        }:
            actual_length = self.safe_int(
                length,
                255,
            )

            return [
                f"        05 {hv:<45} PIC X({actual_length})."
            ]

        if datatype == "DATE":
            return [
                f"        05 {hv:<45} PIC X(10)."
            ]

        if datatype == "TIME":
            return [
                f"        05 {hv:<45} PIC X(8)."
            ]

        if datatype == "TIMESTAMP":
            return [
                f"        05 {hv:<45} PIC X(26)."
            ]

        if datatype in {
            "DECIMAL",
            "NUMERIC",
            "DEC",
        }:
            return self.decimal_to_cobol(
                hv=hv,
                precision=length,
                scale=scale,
            )

        if datatype == "SMALLINT":
            return self.decimal_to_cobol(
                hv=hv,
                precision=4,
                scale=0,
            )

        if datatype in {
            "INTEGER",
            "INT",
        }:
            return self.decimal_to_cobol(
                hv=hv,
                precision=9,
                scale=0,
            )

        if datatype == "BIGINT":
            return self.decimal_to_cobol(
                hv=hv,
                precision=18,
                scale=0,
            )

        if datatype in {
            "DOUBLE",
            "FLOAT",
            "REAL",
        }:
            return [
                f"        05 {hv:<45} COMP-2."
            ]

        actual_length = self.safe_int(
            length,
            255,
        )

        return [
            f"        05 {hv:<45} PIC X({actual_length})."
        ]

    def decimal_to_cobol(
        self,
        hv: str,
        precision: int | None,
        scale: int | None,
    ) -> list[str]:
        actual_precision = self.safe_int(
            precision,
            18,
        )

        actual_scale = self.safe_int(
            scale,
            0,
        )

        integer_digits = max(
            actual_precision - actual_scale,
            1,
        )

        if actual_scale > 0:
            return [
                f"        05 {hv:<45} PIC S9({integer_digits})V9({actual_scale}) COMP-3."
            ]

        return [
            f"        05 {hv:<45} PIC S9({actual_precision}) COMP-3."
        ]

    def safe_int(
        self,
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