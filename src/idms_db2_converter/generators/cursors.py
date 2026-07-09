from idms_db2_converter.exceptions import ConversionError
from idms_db2_converter.generators.formatting import comma_block
from idms_db2_converter.generators.naming import Naming
from idms_db2_converter.models import SchemaModel


class CursorGenerator:
    """
    Generates DECLARE CURSOR statements for IDMS set navigation.

    This version selects all child columns from the final schema so the fetch
    paragraph can populate all host variables needed later by field rewriting.
    """

    def generate(
        self,
        schema: SchemaModel,
        used_sets: list[str]
    ) -> str:

        print("USING CURSOR_GENERATOR VERSION ALL-COLUMNS-2026-07-01")

        blocks: list[str] = []
        seen: set[str] = set()

        for set_name in used_sets:
            set_name = set_name.upper()

            if set_name in seen:
                continue

            seen.add(set_name)

            relationship = schema.relationships.get(set_name)

            if not relationship:
                raise ConversionError(
                    f"Set {set_name} missing from schema relationships."
                )

            if not relationship.parent_key or not relationship.child_fk:
                raise ConversionError(
                    f"Set {set_name} missing parent_key or child_fk."
                )

            child_record = schema.records.get(
                self._physical_record_name(
                    schema,
                    relationship.child_record
                )
            )

            if not child_record:
                raise ConversionError(
                    f"Child record {relationship.child_record} missing."
                )

            columns = list(child_record.fields.keys())

            parent_host = Naming.hv(
                relationship.parent_record,
                relationship.parent_key
            )

            lines = [
                "       EXEC SQL",
                f"            DECLARE {Naming.cursor(set_name)} CURSOR FOR"
            ]

            lines.extend(
                comma_block(
                    items=columns,
                    first_prefix="                SELECT ",
                    next_prefix="                       "
                )
            )

            lines.append(
                f"                  FROM {self._table_name(schema, relationship.child_record)}"
            )

            lines.append(
                f"                 WHERE {relationship.child_fk} = :{parent_host}"
            )

            if relationship.order_by:
                lines.append(
                    f"                 ORDER BY {', '.join(relationship.order_by)}"
                )

            lines.append(
                "       END-EXEC."
            )

            blocks.append(
                "\n".join(lines)
            )

        return "\n\n".join(blocks)

    def _table_name(
        self,
        schema: SchemaModel,
        record_name: str
    ) -> str:

        mapped = schema.record_table_map.get(
            record_name
        )

        if mapped:
            return mapped

        normalized = record_name.replace(
            "-",
            "_"
        ).upper()

        mapped = schema.record_table_map.get(
            normalized
        )

        if mapped:
            return mapped

        return normalized

    def _physical_record_name(
        self,
        schema: SchemaModel,
        logical_record_name: str
    ) -> str:

        logical_record_name = logical_record_name.upper()

        mapped = schema.record_table_map.get(
            logical_record_name
        )

        if mapped and mapped in schema.records:
            return mapped

        normalized = logical_record_name.replace(
            "-",
            "_"
        )

        mapped = schema.record_table_map.get(
            normalized
        )

        if mapped and mapped in schema.records:
            return mapped

        if logical_record_name in schema.records:
            return logical_record_name

        if normalized in schema.records:
            return normalized

        return logical_record_name