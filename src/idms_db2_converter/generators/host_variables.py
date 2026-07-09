from idms_db2_converter.generators.naming import Naming
from idms_db2_converter.models import SchemaModel


class HostVariableGenerator:
    """
    Generates COBOL host variables for DB2 embedded SQL.

    Rules:
    - Generates SQLCA.
    - Generates BEGIN DECLARE SECTION and END DECLARE SECTION.
    - Generates all columns for each used record.
    - Uses Naming.normalize for group names and field names.
    - Converts underscores to hyphens for COBOL data names.
    - Generates null indicators for nullable columns.
    """

    def generate(
        self,
        schema: SchemaModel,
        used_records: list[str],
    ) -> str:
        lines: list[str] = [
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

                lines.extend(
                    self.column_to_cobol(
                        hv=host_variable,
                        datatype=column.datatype,
                        length=column.length,
                        scale=column.scale,
                    )
                )

                if column.nullable:
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

            lines.append(
                "",
            )

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
            return [
                f"        05 {hv:<45} PIC X({length or 1})."
            ]

        if datatype in {
            "VARCHAR",
            "LONG VARCHAR",
        }:
            return [
                f"        05 {hv:<45} PIC X({length or 255})."
            ]

        if datatype in {
            "DATE",
        }:
            return [
                f"        05 {hv:<45} PIC X(10)."
            ]

        if datatype in {
            "TIME",
        }:
            return [
                f"        05 {hv:<45} PIC X(8)."
            ]

        if datatype in {
            "TIMESTAMP",
        }:
            return [
                f"        05 {hv:<45} PIC X(26)."
            ]

        if datatype in {
            "SMALLINT",
        }:
            return [
                f"        05 {hv:<45} PIC S9(4) COMP."
            ]

        if datatype in {
            "INTEGER",
            "INT",
        }:
            return [
                f"        05 {hv:<45} PIC S9(9) COMP."
            ]

        if datatype in {
            "BIGINT",
        }:
            return [
                f"        05 {hv:<45} PIC S9(18) COMP-3."
            ]

        if datatype in {
            "DECIMAL",
            "NUMERIC",
        }:
            return self.decimal_to_cobol(
                hv=hv,
                precision=length,
                scale=scale,
            )

        if datatype in {
            "DOUBLE",
            "FLOAT",
            "REAL",
        }:
            return [
                f"        05 {hv:<45} COMP-2."
            ]

        return [
            f"        05 {hv:<45} PIC X({length or 255})."
        ]

    def decimal_to_cobol(
        self,
        hv: str,
        precision: int | None,
        scale: int | None,
    ) -> list[str]:
        actual_precision = (
            precision
            if precision is not None
            else 18
        )

        actual_scale = (
            scale
            if scale is not None
            else 0
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