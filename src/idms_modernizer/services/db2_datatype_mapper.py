class DB2DatatypeMapper:
    """
    Maps enriched field datatypes to DB2 datatypes.

    Generic behavior only:
    - No field-name-based rules.
    - No hardcoded identifier words.
    - Mapping is based only on datatype, length, and scale.
    """

    @staticmethod
    def map(
        field,
    ) -> str:
        datatype = (
            field.datatype
            or "VARCHAR"
        ).upper()

        length = field.length
        scale = field.scale

        if datatype == "DATE":
            return "DATE"

        if datatype in {
            "TIMESTAMP",
            "DATETIME",
        }:
            return "TIMESTAMP"

        if datatype == "DISPLAY":
            actual_length = (
                length
                if length
                else 255
            )

            if actual_length == 1:
                return "CHAR(1)"

            return f"VARCHAR({actual_length})"

        if datatype == "CHAR":
            actual_length = (
                length
                if length
                else 1
            )

            return f"CHAR({actual_length})"

        if datatype == "VARCHAR":
            actual_length = (
                length
                if length
                else 255
            )

            if actual_length == 1:
                return "CHAR(1)"

            return f"VARCHAR({actual_length})"

        if datatype == "SMALLINT":
            return "SMALLINT"

        if datatype == "INTEGER":
            return "INTEGER"

        if datatype == "BIGINT":
            return "BIGINT"

        if datatype in {
            "DECIMAL",
            "NUMERIC",
            "COMP-3",
        }:
            precision = (
                length
                if length
                else 18
            )

            actual_scale = (
                scale
                if scale is not None
                else 0
            )

            return f"DECIMAL({precision},{actual_scale})"

        if datatype == "COMP":
            return "INTEGER"

        return "VARCHAR(255)"