import json

from idms_db2_converter.exceptions import ConversionError
from idms_db2_converter.models import (
    Column,
    Record,
    Relationship,
    SchemaModel,
)


class Phase2MetadataParser:
    """
    Parses Phase 2 metadata JSON produced by Phase 1.

    Supports:
    - records / tables / db2_tables
    - relationships / sets / db2_relationships
    - record_table_map
    - field_map
    - calc_key_map
    - set_ordering_map
    - navigation_intent
    - nullable_fk_map
    - date_part_map
    - output_semantics
    - paragraph_operation_graph
    - validation_messages
    """

    def parse_as_schema(
        self,
        text: str
    ) -> SchemaModel:

        schema = SchemaModel()

        if not text or not text.strip():
            return schema

        payload = self._load_payload(text)

        self._parse_metadata_records(
            payload=payload,
            schema=schema
        )

        self._parse_metadata_relationships(
            payload=payload,
            schema=schema,
            merge_existing=False
        )

        self.parse_into_schema(
            text=text,
            schema=schema
        )

        schema.schema_source = "PHASE2_METADATA"

        return schema

    def parse_into_schema(
        self,
        text: str,
        schema: SchemaModel
    ) -> SchemaModel:

        if not text or not text.strip():
            return schema

        payload = self._load_payload(text)

        self._merge_record_table_map(
            payload=payload,
            schema=schema
        )

        self._merge_field_map(
            payload=payload,
            schema=schema
        )

        self._merge_calc_key_map(
            payload=payload,
            schema=schema
        )

        self._merge_set_ordering_map(
            payload=payload,
            schema=schema
        )

        self._merge_navigation_intent(
            payload=payload,
            schema=schema
        )

        self._merge_nullable_fk_map(
            payload=payload,
            schema=schema
        )

        self._merge_date_part_map(
            payload=payload,
            schema=schema
        )

        self._merge_output_semantics(
            payload=payload,
            schema=schema
        )

        self._merge_paragraph_operation_graph(
            payload=payload,
            schema=schema
        )

        self._parse_metadata_relationships(
            payload=payload,
            schema=schema,
            merge_existing=True
        )

        self._merge_validation_messages(
            payload=payload,
            schema=schema
        )

        self._apply_set_ordering(
            schema
        )

        return schema

    def _load_payload(
        self,
        text: str
    ) -> dict:

        try:
            return json.loads(text)

        except json.JSONDecodeError as exc:
            raise ConversionError(
                f"Invalid Phase 2 metadata JSON: {exc}"
            ) from exc

    def _parse_metadata_records(
        self,
        payload: dict,
        schema: SchemaModel
    ) -> None:

        records_payload = (
            payload.get("records")
            or payload.get("tables")
            or payload.get("db2_tables")
            or []
        )

        for record_json in records_payload:
            record_name = (
                record_json.get("name")
                or record_json.get("record")
                or record_json.get("table")
            )

            if not record_name:
                continue

            record_name = self._normalize_record_name(
                record_name
            )

            primary_key = (
                record_json.get("primary_key")
                or record_json.get("pk")
            )

            primary_key = (
                self._normalize_column_name(primary_key)
                if primary_key
                else None
            )

            fields = {}

            fields_payload = (
                record_json.get("fields")
                or record_json.get("columns")
                or []
            )

            for field_json in fields_payload:
                field_name = (
                    field_json.get("name")
                    or field_json.get("column")
                )

                if not field_name:
                    continue

                field_name = self._normalize_column_name(
                    field_name
                )

                datatype = (
                    field_json.get("datatype")
                    or field_json.get("type")
                    or "CHAR"
                )

                datatype = str(datatype).upper()

                length = field_json.get("length")
                scale = field_json.get("scale")

                nullable = field_json.get("nullable")

                if nullable is None:
                    nullable = field_name != primary_key

                fields[field_name] = Column(
                    name=field_name,
                    datatype=datatype,
                    length=length,
                    scale=scale,
                    nullable=bool(nullable)
                )

            schema.records[record_name] = Record(
                name=record_name,
                primary_key=primary_key,
                fields=fields
            )

            table_name = (
                record_json.get("table")
                or record_name
            )

            schema.record_table_map[record_name] = self._normalize_record_name(
                table_name
            )

    def _parse_metadata_relationships(
        self,
        payload: dict,
        schema: SchemaModel,
        merge_existing: bool
    ) -> None:

        relationships_payload = (
            payload.get("relationships")
            or payload.get("sets")
            or payload.get("db2_relationships")
            or []
        )

        for relationship_json in relationships_payload:
            set_name = (
                relationship_json.get("set_name")
                or relationship_json.get("name")
                or relationship_json.get("relationship")
            )

            parent_record = (
                relationship_json.get("parent_record")
                or relationship_json.get("parent_table")
            )

            child_record = (
                relationship_json.get("child_record")
                or relationship_json.get("child_table")
            )

            if not set_name:
                continue

            if not parent_record:
                continue

            if not child_record:
                continue

            set_name = self._normalize_set_name(
                set_name
            )

            parent_record = self._normalize_record_name(
                parent_record
            )

            child_record = self._normalize_record_name(
                child_record
            )

            parent_key = (
                relationship_json.get("parent_key")
                or relationship_json.get("parent_pk")
            )

            child_fk = (
                relationship_json.get("child_fk")
                or relationship_json.get("foreign_key")
            )

            parent_key = (
                self._normalize_column_name(parent_key)
                if parent_key
                else None
            )

            child_fk = (
                self._normalize_column_name(child_fk)
                if child_fk
                else None
            )

            if not parent_key:
                parent_key = self._resolve_parent_key(
                    schema=schema,
                    parent_record=parent_record
                )

            if not child_fk:
                child_fk = self._resolve_child_fk(
                    schema=schema,
                    parent_record=parent_record,
                    child_record=child_record,
                    parent_key=parent_key
                )

            order_by = [
                self._normalize_column_name(value)
                for value in relationship_json.get("order_by", [])
                if value
            ]

            if not order_by and child_fk:
                order_by = [
                    child_fk
                ]

            for alias in self._set_name_aliases(set_name):
                self._upsert_relationship(
                    schema=schema,
                    set_name=alias,
                    parent_record=parent_record,
                    child_record=child_record,
                    parent_key=parent_key,
                    child_fk=child_fk,
                    cardinality=relationship_json.get(
                        "cardinality",
                        "1:N"
                    ),
                    order_by=order_by,
                    merge_existing=merge_existing
                )

    def _upsert_relationship(
        self,
        schema: SchemaModel,
        set_name: str,
        parent_record: str,
        child_record: str,
        parent_key: str | None,
        child_fk: str | None,
        cardinality: str | None,
        order_by: list[str],
        merge_existing: bool
    ) -> None:

        if merge_existing and set_name in schema.relationships:
            relationship = schema.relationships[set_name]

            if parent_record:
                relationship.parent_record = parent_record

            if child_record:
                relationship.child_record = child_record

            if parent_key:
                relationship.parent_key = parent_key

            if child_fk:
                relationship.child_fk = child_fk

            if cardinality:
                relationship.cardinality = cardinality

            if order_by:
                relationship.order_by = order_by

            return

        schema.relationships[set_name] = Relationship(
            set_name=set_name,
            parent_record=parent_record,
            child_record=child_record,
            cardinality=cardinality or "1:N",
            parent_key=parent_key,
            child_fk=child_fk,
            order_by=order_by
        )

    def _merge_record_table_map(
        self,
        payload: dict,
        schema: SchemaModel
    ) -> None:

        for key, value in payload.get("record_table_map", {}).items():
            schema.record_table_map[str(key).upper()] = (
                str(value).upper()
                if isinstance(value, str)
                else value
            )

    def _merge_field_map(
        self,
        payload: dict,
        schema: SchemaModel
    ) -> None:

        for key, value in payload.get("field_map", {}).items():
            schema.field_map[str(key).upper()] = value

    def _merge_calc_key_map(
        self,
        payload: dict,
        schema: SchemaModel
    ) -> None:

        for key, value in payload.get("calc_key_map", {}).items():
            schema.calc_key_map[str(key).upper()] = value

    def _merge_set_ordering_map(
        self,
        payload: dict,
        schema: SchemaModel
    ) -> None:

        for key, value in payload.get("set_ordering_map", {}).items():
            for alias in self._set_name_aliases(str(key)):
                schema.set_ordering_map[alias] = value

    def _merge_navigation_intent(
        self,
        payload: dict,
        schema: SchemaModel
    ) -> None:

        for key, value in payload.get("navigation_intent", {}).items():
            for alias in self._set_name_aliases(str(key)):
                schema.navigation_intent[alias] = value

    def _merge_nullable_fk_map(
        self,
        payload: dict,
        schema: SchemaModel
    ) -> None:

        for key, value in payload.get("nullable_fk_map", {}).items():
            schema.nullable_fk_map[str(key).upper()] = value

    def _merge_date_part_map(
        self,
        payload: dict,
        schema: SchemaModel
    ) -> None:

        for key, value in payload.get("date_part_map", {}).items():
            schema.date_part_map[str(key).upper()] = value

    def _merge_output_semantics(
        self,
        payload: dict,
        schema: SchemaModel
    ) -> None:

        output_semantics = payload.get("output_semantics", {})

        if output_semantics:
            schema.output_semantics.update(output_semantics)

    def _merge_paragraph_operation_graph(
        self,
        payload: dict,
        schema: SchemaModel
    ) -> None:

        for key, value in payload.get("paragraph_operation_graph", {}).items():
            schema.paragraph_operation_graph[str(key).upper()] = value

    def _merge_validation_messages(
        self,
        payload: dict,
        schema: SchemaModel
    ) -> None:

        validation_messages = payload.get("validation_messages", [])

        if validation_messages and hasattr(schema, "validation_messages"):
            schema.validation_messages.extend(validation_messages)

    def _apply_set_ordering(
        self,
        schema: SchemaModel
    ) -> None:

        for set_name, ordering in schema.set_ordering_map.items():
            relationship = schema.relationships.get(set_name)

            if not relationship:
                continue

            order_by = ordering.get("order_by", [])

            if order_by:
                relationship.order_by = [
                    self._normalize_column_name(item)
                    for item in order_by
                ]

    def _resolve_parent_key(
        self,
        schema: SchemaModel,
        parent_record: str
    ) -> str | None:

        record = schema.records.get(parent_record)

        if not record:
            return None

        return record.primary_key

    def _resolve_child_fk(
        self,
        schema: SchemaModel,
        parent_record: str,
        child_record: str,
        parent_key: str | None
    ) -> str | None:

        child = schema.records.get(child_record)

        if not child:
            return None

        if parent_key and parent_key in child.fields:
            return parent_key

        parent = schema.records.get(parent_record)

        if parent and parent.primary_key and parent.primary_key in child.fields:
            return parent.primary_key

        return None

    def _normalize_record_name(
        self,
        value: str | None
    ) -> str:

        if not value:
            return ""

        return str(value).strip().upper().replace("-", "_")

    def _normalize_column_name(
        self,
        value: str | None
    ) -> str:

        if not value:
            return ""

        return str(value).strip().upper().replace("-", "_")

    def _normalize_set_name(
        self,
        value: str | None
    ) -> str:

        if not value:
            return ""

        return str(value).strip().upper()

    def _set_name_aliases(
        self,
        value: str | None
    ) -> list[str]:

        if not value:
            return []

        raw = str(value).strip().upper()
        hyphen = raw.replace("_", "-")
        underscore = raw.replace("-", "_")

        aliases = []

        for item in [
            raw,
            hyphen,
            underscore
        ]:
            if item not in aliases:
                aliases.append(item)

        return aliases