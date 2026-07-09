import json

from idms_db2_converter.exceptions import ConversionError
from idms_db2_converter.models import Column, Record, Relationship, SchemaModel


class CanonicalParser:
    def parse(self, text: str) -> SchemaModel:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConversionError(f"Invalid canonical JSON: {exc}") from exc

        schema = SchemaModel()

        self._parse_records(payload, schema)
        self._parse_relationships(payload, schema)
        self._parse_field_map(payload, schema)

        return schema

    def _parse_records(self, payload: dict, schema: SchemaModel) -> None:
        for record_json in payload.get("records", []):
            record_name = record_json["name"].upper()
            primary_key = self._upper_or_none(record_json.get("primary_key"))

            fields = {}

            for field_json in record_json.get("fields", []):
                field_name = field_json["name"].upper()

                nullable = field_json.get("nullable")
                if nullable is None:
                    nullable = field_name != primary_key

                fields[field_name] = Column(
                    name=field_name,
                    datatype=field_json["datatype"].upper(),
                    length=field_json.get("length"),
                    scale=field_json.get("scale"),
                    nullable=bool(nullable),
                )

            schema.records[record_name] = Record(
                name=record_name,
                primary_key=primary_key,
                fields=fields,
            )

    def _parse_relationships(self, payload: dict, schema: SchemaModel) -> None:
        for rel_json in payload.get("relationships", []):
            set_name = rel_json["set_name"].upper()
            parent_record = rel_json["parent_record"].upper()
            child_record = rel_json["child_record"].upper()

            parent_key = self._upper_or_none(rel_json.get("parent_key"))
            child_fk = self._upper_or_none(rel_json.get("child_fk"))

            if not parent_key:
                parent_key = self._resolve_parent_key(schema, parent_record)

            if not child_fk:
                child_fk = self._resolve_child_fk(
                    schema=schema,
                    parent_record=parent_record,
                    child_record=child_record,
                )

            order_by = [
                value.upper()
                for value in rel_json.get("order_by", [])
            ]

            if not order_by and child_fk:
                order_by = [child_fk]

            schema.relationships[set_name] = Relationship(
                set_name=set_name,
                parent_record=parent_record,
                child_record=child_record,
                cardinality=rel_json.get("cardinality"),
                parent_key=parent_key,
                child_fk=child_fk,
                order_by=order_by,
            )

    def _parse_field_map(self, payload: dict, schema: SchemaModel) -> None:
        schema.field_map = {
            key.upper(): value
            for key, value in payload.get("field_map", {}).items()
        }

    def _resolve_parent_key(
        self,
        schema: SchemaModel,
        parent_record: str,
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
    ) -> str | None:
        parent = schema.records.get(parent_record)
        child = schema.records.get(child_record)

        if not parent or not child or not parent.primary_key:
            return None

        if parent.primary_key in child.fields:
            return parent.primary_key

        return None

    def _upper_or_none(self, value: str | None) -> str | None:
        return value.upper() if value else None