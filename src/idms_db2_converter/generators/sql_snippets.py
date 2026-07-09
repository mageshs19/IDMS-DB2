from idms_db2_converter.exceptions import ConversionError
from idms_db2_converter.generators.formatting import comma_block
from idms_db2_converter.generators.naming import Naming
from idms_db2_converter.models import SchemaModel


class SqlSnippets:
    """
    Generates embedded SQL snippets with full SELECT and INTO lists.
    """

    def __init__(
        self,
        schema: SchemaModel
    ):
        self.schema = schema

    def select_for_record_by_pk(
        self,
        record_name: str
    ) -> str:

        physical_record_name = self.physical_record_name(
            record_name
        )

        record = self.schema.records.get(
            physical_record_name
        )

        if not record:
            raise ConversionError(
                f"Record {record_name} missing from schema."
            )

        if not record.primary_key:
            raise ConversionError(
                f"Record {record_name} has no primary key."
            )

        columns = list(record.fields.keys())

        into_items = [
            self.host_with_indicator(
                logical_record_name=record_name,
                column_name=column_name,
                nullable=record.fields[column_name].nullable
            )
            for column_name in columns
        ]

        lines = [
            "EXEC SQL"
        ]

        lines.extend(
            comma_block(
                items=columns,
                first_prefix="    SELECT ",
                next_prefix="           "
            )
        )

        lines.extend(
            comma_block(
                items=into_items,
                first_prefix="      INTO ",
                next_prefix="           "
            )
        )

        lines.append(
            f"      FROM {physical_record_name}"
        )

        lines.append(
            f"     WHERE {record.primary_key} = :{Naming.hv(record_name, record.primary_key)}"
        )

        lines.append(
            "END-EXEC."
        )

        return "\n".join(lines)

    def select_first_child_for_set(
        self,
        set_name: str
    ) -> str:

        set_name = set_name.upper()

        relationship = self.schema.relationships.get(
            set_name
        )

        if not relationship:
            raise ConversionError(
                f"Set {set_name} missing from schema relationships."
            )

        child_record_name = self.physical_record_name(
            relationship.child_record
        )

        child_record = self.schema.records.get(
            child_record_name
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
                nullable=child_record.fields[column_name].nullable
            )
            for column_name in columns
        ]

        parent_host = Naming.hv(
            relationship.parent_record,
            relationship.parent_key
        )

        lines = [
            "EXEC SQL"
        ]

        lines.extend(
            comma_block(
                items=columns,
                first_prefix="    SELECT ",
                next_prefix="           "
            )
        )

        lines.extend(
            comma_block(
                items=into_items,
                first_prefix="      INTO ",
                next_prefix="           "
            )
        )

        lines.append(
            f"      FROM {child_record_name}"
        )

        lines.append(
            f"     WHERE {relationship.child_fk} = :{parent_host}"
        )

        if relationship.order_by:
            lines.append(
                f"  ORDER BY {', '.join(relationship.order_by)}"
            )

        lines.append(
            " FETCH FIRST 1 ROW ONLY"
        )

        lines.append(
            "END-EXEC."
        )

        return "\n".join(lines)

    def select_for_owner(
        self,
        set_name: str
    ) -> str:

        set_name = set_name.upper()

        relationship = self.schema.relationships.get(
            set_name
        )

        if not relationship:
            raise ConversionError(
                f"Set {set_name} missing from schema relationships."
            )

        parent_record_name = self.physical_record_name(
            relationship.parent_record
        )

        parent_record = self.schema.records.get(
            parent_record_name
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
                nullable=parent_record.fields[column_name].nullable
            )
            for column_name in columns
        ]

        child_host = Naming.hv(
            relationship.child_record,
            relationship.child_fk
        )

        lines = [
            "EXEC SQL"
        ]

        lines.extend(
            comma_block(
                items=columns,
                first_prefix="    SELECT ",
                next_prefix="           "
            )
        )

        lines.extend(
            comma_block(
                items=into_items,
                first_prefix="      INTO ",
                next_prefix="           "
            )
        )

        lines.append(
            f"      FROM {parent_record_name}"
        )

        lines.append(
            f"     WHERE {relationship.parent_key} = :{child_host}"
        )

        lines.append(
            "END-EXEC."
        )

        return "\n".join(lines)

    def fetch_for_set(
        self,
        set_name: str
    ) -> str:

        set_name = set_name.upper()

        relationship = self.schema.relationships.get(
            set_name
        )

        if not relationship:
            raise ConversionError(
                f"Set {set_name} missing from schema relationships."
            )

        child_record_name = self.physical_record_name(
            relationship.child_record
        )

        child_record = self.schema.records.get(
            child_record_name
        )

        if not child_record:
            raise ConversionError(
                f"Child record {relationship.child_record} missing from schema."
            )

        into_items = [
            self.host_with_indicator(
                logical_record_name=relationship.child_record,
                column_name=column_name,
                nullable=column.nullable
            )
            for column_name, column in child_record.fields.items()
        ]

        lines = [
            "EXEC SQL",
            f"    FETCH {Naming.cursor(set_name)}"
        ]

        lines.extend(
            comma_block(
                items=into_items,
                first_prefix="     INTO ",
                next_prefix="          "
            )
        )

        lines.append(
            "END-EXEC."
        )

        return "\n".join(lines)

    def nullable_fk_indicator_for_set(
        self,
        set_name: str
    ) -> str | None:

        relationship = self.schema.relationships.get(
            set_name.upper()
        )

        if not relationship:
            return None

        child_record_name = self.physical_record_name(
            relationship.child_record
        )

        child_record = self.schema.records.get(
            child_record_name
        )

        if not child_record:
            return None

        child_fk = relationship.child_fk

        if not child_fk:
            return None

        column = child_record.fields.get(
            child_fk
        )

        if not column:
            return None

        if not column.nullable:
            return None

        return Naming.ni(
            relationship.child_record,
            child_fk
        )

    def physical_record_name(
        self,
        logical_record_name: str
    ) -> str:

        logical_record_name = logical_record_name.upper()

        mapped = self.schema.record_table_map.get(
            logical_record_name
        )

        if mapped and mapped in self.schema.records:
            return mapped

        normalized = logical_record_name.replace(
            "-",
            "_"
        )

        mapped = self.schema.record_table_map.get(
            normalized
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
        nullable: bool
    ) -> str:

        host = f":{Naming.hv(logical_record_name, column_name)}"

        if nullable:
            host = f"{host} :{Naming.ni(logical_record_name, column_name)}"

        return host