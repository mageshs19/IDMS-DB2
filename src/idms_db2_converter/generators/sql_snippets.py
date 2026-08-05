from idms_db2_converter.exceptions import ConversionError
from idms_db2_converter.generators.formatting import comma_block
from idms_db2_converter.generators.naming import Naming
from idms_db2_converter.models import SchemaModel


class SqlSnippets:
    """
    Generates embedded SQL snippets with full SELECT and INTO lists.

    Composite-key support:
    - OBTAIN CALC uses all effective primary keys.
    - FIND FIRST / first child lookup uses all parent_keys and child_fks.
    - OBTAIN OWNER uses all parent_keys and child_fks.
    - Backward compatible with parent_key / child_fk / primary_key.

    Nullable FK support:
    - nullable_fk_indicator_for_set() finds the first nullable child FK and
      returns its generated null indicator.
    """

    def __init__(
        self,
        schema: SchemaModel,
    ):
        self.schema = schema

    def select_for_record_by_pk(
        self,
        record_name: str,
    ) -> str:
        physical_record_name = self.physical_record_name(
            record_name,
        )

        record = self.schema.records.get(
            physical_record_name,
        )

        if not record:
            raise ConversionError(
                f"Record {record_name} missing from schema."
            )

        primary_keys = self.effective_primary_keys(
            record=record,
        )

        if not primary_keys:
            raise ConversionError(
                f"Record {record_name} has no primary key."
            )

        columns = list(record.fields.keys())

        into_items = [
            self.host_with_indicator(
                logical_record_name=record_name,
                column_name=column_name,
                nullable=record.fields[column_name].nullable,
            )
            for column_name in columns
        ]

        where_items = [
            f"{primary_key} = :{Naming.hv(record_name, primary_key)}"
            for primary_key in primary_keys
        ]

        lines = [
            "EXEC SQL",
        ]

        lines.extend(
            comma_block(
                items=columns,
                first_prefix="SELECT ",
                next_prefix="       ",
            )
        )

        lines.extend(
            comma_block(
                items=into_items,
                first_prefix="INTO ",
                next_prefix="     ",
            )
        )

        lines.append(
            f"FROM {physical_record_name}"
        )

        lines.extend(
            self.where_lines(
                where_items=where_items,
            )
        )

        lines.append(
            "END-EXEC."
        )

        return "\n".join(lines)

    def select_first_child_for_set(
        self,
        set_name: str,
    ) -> str:
        set_name = set_name.upper()

        relationship = self.schema.relationships.get(
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

        child_record_name = self.physical_record_name(
            relationship.child_record,
        )

        child_record = self.schema.records.get(
            child_record_name,
        )

        if not child_record:
            raise ConversionError(
                f"Child record {relationship.child_record} missing from schema."
            )

        columns = list(child_record.fields.keys())

        into_items = [
            self.host_with_indicator(
                logical_record_name=relationship.child_record,
                column_name=column_name,
                nullable=child_record.fields[column_name].nullable,
            )
            for column_name in columns
        ]

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
        ]

        lines.extend(
            comma_block(
                items=columns,
                first_prefix="SELECT ",
                next_prefix="       ",
            )
        )

        lines.extend(
            comma_block(
                items=into_items,
                first_prefix="INTO ",
                next_prefix="     ",
            )
        )

        lines.append(
            f"FROM {child_record_name}"
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
            "FETCH FIRST 1 ROW ONLY"
        )

        lines.append(
            "END-EXEC."
        )

        return "\n".join(lines)

    def select_for_owner(
        self,
        set_name: str,
    ) -> str:
        set_name = set_name.upper()

        relationship = self.schema.relationships.get(
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

        parent_record_name = self.physical_record_name(
            relationship.parent_record,
        )

        parent_record = self.schema.records.get(
            parent_record_name,
        )

        if not parent_record:
            raise ConversionError(
                f"Parent record {relationship.parent_record} missing from schema."
            )

        columns = list(parent_record.fields.keys())

        into_items = [
            self.host_with_indicator(
                logical_record_name=relationship.parent_record,
                column_name=column_name,
                nullable=parent_record.fields[column_name].nullable,
            )
            for column_name in columns
        ]

        where_items = []

        for parent_key, child_fk in zip(parent_keys, child_fks):
            child_host = Naming.hv(
                relationship.child_record,
                child_fk,
            )

            where_items.append(
                f"{parent_key} = :{child_host}"
            )

        lines = [
            "EXEC SQL",
        ]

        lines.extend(
            comma_block(
                items=columns,
                first_prefix="SELECT ",
                next_prefix="       ",
            )
        )

        lines.extend(
            comma_block(
                items=into_items,
                first_prefix="INTO ",
                next_prefix="     ",
            )
        )

        lines.append(
            f"FROM {parent_record_name}"
        )

        lines.extend(
            self.where_lines(
                where_items=where_items,
            )
        )

        lines.append(
            "END-EXEC."
        )

        return "\n".join(lines)

    def fetch_for_set(
        self,
        set_name: str,
    ) -> str:
        set_name = set_name.upper()

        relationship = self.schema.relationships.get(
            set_name,
        )

        if not relationship:
            raise ConversionError(
                f"Set {set_name} missing from schema relationships."
            )

        child_record_name = self.physical_record_name(
            relationship.child_record,
        )

        child_record = self.schema.records.get(
            child_record_name,
        )

        if not child_record:
            raise ConversionError(
                f"Child record {relationship.child_record} missing from schema."
            )

        into_items = [
            self.host_with_indicator(
                logical_record_name=relationship.child_record,
                column_name=column_name,
                nullable=column.nullable,
            )
            for column_name, column in child_record.fields.items()
        ]

        lines = [
            "EXEC SQL",
            f"FETCH {Naming.cursor(set_name)}",
        ]

        lines.extend(
            comma_block(
                items=into_items,
                first_prefix="INTO ",
                next_prefix="     ",
            )
        )

        lines.append(
            "END-EXEC."
        )

        return "\n".join(lines)

    def nullable_fk_indicator_for_set(
        self,
        set_name: str,
    ) -> str | None:
        set_name = set_name.upper()

        relationship = self.schema.relationships.get(
            set_name,
        )

        if not relationship:
            return None

        child_record_name = self.physical_record_name(
            relationship.child_record,
        )

        child_record = self.schema.records.get(
            child_record_name,
        )

        if not child_record:
            return None

        child_fks = self.effective_child_fks(
            relationship=relationship,
        )

        for child_fk in child_fks:
            column = child_record.fields.get(
                child_fk,
            )

            if not column:
                continue

            if getattr(column, "nullable", True):
                return Naming.ni(
                    relationship.child_record,
                    child_fk,
                )

        return None

    def effective_primary_keys(
        self,
        record,
    ) -> list[str]:
        if hasattr(record, "effective_primary_keys"):
            keys = record.effective_primary_keys()
        else:
            keys = list(getattr(record, "primary_keys", []) or [])

            if getattr(record, "primary_key", None):
                if record.primary_key not in keys:
                    keys.append(record.primary_key)

        return [
            key
            for key in keys
            if key
        ]

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

    def physical_record_name(
        self,
        logical_record_name: str,
    ) -> str:
        logical_record_name = logical_record_name.upper()

        mapped = self.schema.record_table_map.get(
            logical_record_name,
        )

        if mapped and mapped in self.schema.records:
            return mapped

        normalized = logical_record_name.replace(
            "-",
            "_",
        )

        mapped = self.schema.record_table_map.get(
            normalized,
        )

        if mapped and mapped in self.schema.records:
            return mapped

        if logical_record_name in self.schema.records:
            return logical_record_name

        if normalized in self.schema.records:
            return normalized

        return logical_record_name

    def host_with_indicator(
        self,
        logical_record_name: str,
        column_name: str,
        nullable: bool,
    ) -> str:
        host = f":{Naming.hv(logical_record_name, column_name)}"

        if nullable:
            host += f" :{Naming.ni(logical_record_name, column_name)}"

        return host