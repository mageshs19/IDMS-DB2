from idms_db2_converter.exceptions import ConversionError
from idms_db2_converter.generators.formatting import comma_block
from idms_db2_converter.generators.naming import Naming
from idms_db2_converter.models import SchemaModel


class CursorGenerator:
    """
    Generates DECLARE CURSOR statements for IDMS set navigation.

    Composite-key support:
    - Uses relationship.parent_keys / relationship.child_fks when available.
    - Falls back to relationship.parent_key / relationship.child_fk.
    - WHERE clause emits all FK-to-parent-host conditions.
    """

    def generate(
        self,
        schema: SchemaModel,
        used_sets: list[str],
    ) -> str:
        print("USING CURSOR_GENERATOR VERSION COMPOSITE-KEYS-2026-08-05")

        blocks: list[str] = []
        seen: set[str] = set()

        for set_name in used_sets:
            set_name = set_name.upper()

            if set_name in seen:
                continue

            seen.add(set_name)

            relationship = schema.relationships.get(
                set_name,
            )

            if not relationship:
                raise ConversionError(
                    f"Set {set_name} missing from schema relationships."
                )

            parent_keys = self.effective_parent_keys(
                relationship=relationship,
            )

            child_fks = self.effective_child_fks(
                relationship=relationship,
            )

            self.validate_key_pairing(
                set_name=set_name,
                parent_keys=parent_keys,
                child_fks=child_fks,
            )

            child_record = schema.records.get(
                self._physical_record_name(
                    schema=schema,
                    logical_record_name=relationship.child_record,
                )
            )

            if not child_record:
                raise ConversionError(
                    f"Child record {relationship.child_record} missing."
                )

            columns = list(child_record.fields.keys())

            where_items = []

            for parent_key, child_fk in zip(parent_keys, child_fks):
                parent_host = Naming.hv(
                    relationship.parent_record,
                    parent_key,
                )

                where_items.append(
                    f"{child_fk} = :{parent_host}"
                )

            order_by = relationship.order_by or child_fks

            lines = [
                "EXEC SQL",
                f"DECLARE {Naming.cursor(set_name)} CURSOR FOR",
            ]

            lines.extend(
                comma_block(
                    items=columns,
                    first_prefix="SELECT ",
                    next_prefix="       ",
                )
            )

            lines.append(
                f"FROM {self._physical_record_name(schema, relationship.child_record)}"
            )

            lines.extend(
                self.where_lines(
                    where_items=where_items,
                )
            )

            if order_by:
                lines.append(
                    f"ORDER BY {', '.join(order_by)}"
                )

            lines.append(
                "END-EXEC."
            )

            blocks.append(
                "\n".join(lines)
            )

        return "\n\n".join(blocks)

    def effective_parent_keys(
        self,
        relationship,
    ) -> list[str]:
        if hasattr(relationship, "effective_parent_keys"):
            keys = relationship.effective_parent_keys()
        else:
            keys = list(getattr(relationship, "parent_keys", []) or [])

            if getattr(relationship, "parent_key", None):
                if relationship.parent_key not in keys:
                    keys.append(relationship.parent_key)

        return [
            key
            for key in keys
            if key
        ]

    def effective_child_fks(
        self,
        relationship,
    ) -> list[str]:
        if hasattr(relationship, "effective_child_fks"):
            keys = relationship.effective_child_fks()
        else:
            keys = list(getattr(relationship, "child_fks", []) or [])

            if getattr(relationship, "child_fk", None):
                if relationship.child_fk not in keys:
                    keys.append(relationship.child_fk)

        return [
            key
            for key in keys
            if key
        ]

    def validate_key_pairing(
        self,
        set_name: str,
        parent_keys: list[str],
        child_fks: list[str],
    ) -> None:
        if not parent_keys:
            raise ConversionError(
                f"Set {set_name} missing parent_key or parent_keys."
            )

        if not child_fks:
            raise ConversionError(
                f"Set {set_name} missing child_fk or child_fks."
            )

        if len(parent_keys) != len(child_fks):
            raise ConversionError(
                f"Set {set_name} has mismatched composite keys: "
                f"{len(parent_keys)} parent key(s), {len(child_fks)} child FK(s)."
            )

    def where_lines(
        self,
        where_items: list[str],
    ) -> list[str]:
        lines = []

        for index, item in enumerate(where_items):
            if index == 0:
                lines.append(
                    f"WHERE {item}"
                )
            else:
                lines.append(
                    f"  AND {item}"
                )

        return lines

    def _physical_record_name(
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

        return logical_record_name