import json

from typing import Any

from idms_db2_converter.exceptions import ConversionError
from idms_db2_converter.models import Column, Record, Relationship, SchemaModel


class CanonicalParser:
    """
    Parses canonical JSON into SchemaModel.

    Fixes:
    - Avoids calling .upper() on None.
    - Handles fields with null datatype.
    - Skips incomplete relationships safely.
    - Supports primary_key and primary_keys.
    - Preserves field_map when present.
    """

    DEFAULT_DATATYPE = "CHAR"

    def parse(
        self,
        text: str,
    ) -> SchemaModel:
        if not text or not text.strip():
            return SchemaModel()

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConversionError(f"Invalid canonical JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise ConversionError("Invalid canonical JSON: root must be an object.")

        schema = SchemaModel()

        self._parse_records(
            payload=payload,
            schema=schema,
        )

        self._parse_relationships(
            payload=payload,
            schema=schema,
        )

        self._parse_field_map(
            payload=payload,
            schema=schema,
        )

        return schema

    def _parse_records(
        self,
        payload: dict,
        schema: SchemaModel,
    ) -> None:
        records = payload.get("records") or []

        if isinstance(records, dict):
            records = list(records.values())

        for record_json in records:
            if not isinstance(record_json, dict):
                continue

            record_name = self._upper_or_empty(
                self._first_non_empty(
                    record_json,
                    [
                        "name",
                        "record",
                        "record_name",
                        "table",
                        "table_name",
                    ],
                )
            )

            if not record_name:
                continue

            primary_keys = self._extract_primary_keys(record_json)
            primary_key = primary_keys[0] if primary_keys else None

            fields: dict[str, Column] = {}

            field_items = (
                record_json.get("fields")
                or record_json.get("columns")
                or record_json.get("db2_columns")
                or []
            )

            if isinstance(field_items, dict):
                field_items = list(field_items.values())

            for field_json in field_items:
                if not isinstance(field_json, dict):
                    continue

                field_name = self._upper_or_empty(
                    self._first_non_empty(
                        field_json,
                        [
                            "name",
                            "field",
                            "column",
                            "column_name",
                        ],
                    )
                )

                if not field_name:
                    continue

                datatype = self._upper_or_empty(
                    self._first_non_empty(
                        field_json,
                        [
                            "datatype",
                            "data_type",
                            "type",
                            "db2_datatype",
                        ],
                    )
                )

                if not datatype:
                    datatype = self.DEFAULT_DATATYPE

                nullable = field_json.get("nullable")

                if nullable is None:
                    nullable = field_name != primary_key

                primary_key_flag = bool(field_json.get("primary_key", False))

                if field_name in primary_keys:
                    primary_key_flag = True
                    nullable = False

                fields[field_name] = Column(
                    name=field_name,
                    datatype=datatype,
                    length=field_json.get("length"),
                    scale=field_json.get("scale"),
                    nullable=bool(nullable),
                    primary_key=primary_key_flag,
                    generated=bool(field_json.get("generated", False)),
                    source_kind=str(field_json.get("source_kind", "") or ""),
                )

            record = Record(
                name=record_name,
                primary_key=primary_key,
                fields=fields,
                primary_keys=primary_keys,
            )

            if hasattr(record, "set_primary_keys"):
                record.set_primary_keys(primary_keys)

            schema.records[record_name] = record

    def _parse_relationships(
        self,
        payload: dict,
        schema: SchemaModel,
    ) -> None:
        relationships = (
            payload.get("relationships")
            or payload.get("sets")
            or payload.get("db2_relationships")
            or []
        )

        if isinstance(relationships, dict):
            relationships = list(relationships.values())

        for rel_json in relationships:
            if not isinstance(rel_json, dict):
                continue

            set_name = self._upper_or_empty(
                self._first_non_empty(
                    rel_json,
                    [
                        "set_name",
                        "name",
                        "set",
                        "relationship",
                    ],
                )
            )

            parent_record = self._upper_or_empty(
                self._first_non_empty(
                    rel_json,
                    [
                        "parent_record",
                        "owner_record",
                        "parent",
                        "owner",
                        "parent_table",
                    ],
                )
            )

            child_record = self._upper_or_empty(
                self._first_non_empty(
                    rel_json,
                    [
                        "child_record",
                        "member_record",
                        "child",
                        "member",
                        "child_table",
                    ],
                )
            )

            if not set_name or not parent_record or not child_record:
                continue

            parent_keys = self._extract_key_list(
                source=rel_json,
                plural_keys=[
                    "parent_keys",
                    "owner_keys",
                ],
                single_keys=[
                    "parent_key",
                    "owner_key",
                    "parent_pk",
                ],
            )

            child_fks = self._extract_key_list(
                source=rel_json,
                plural_keys=[
                    "child_fks",
                    "member_fks",
                    "foreign_keys",
                ],
                single_keys=[
                    "child_fk",
                    "member_fk",
                    "foreign_key",
                    "child_pk",
                ],
            )

            parent_key = parent_keys[0] if parent_keys else None
            child_fk = child_fks[0] if child_fks else None

            if not parent_key:
                parent_key = self._resolve_parent_key(
                    schema=schema,
                    parent_record=parent_record,
                )

                if parent_key:
                    parent_keys = [parent_key]

            if not child_fk:
                child_fk = self._resolve_child_fk(
                    schema=schema,
                    parent_record=parent_record,
                    child_record=child_record,
                    parent_keys=parent_keys,
                )

                if child_fk:
                    child_fks = [child_fk]

            order_by = [
                self._upper_or_empty(value)
                for value in rel_json.get("order_by", []) or []
                if self._upper_or_empty(value)
            ]

            if not order_by and child_fks:
                order_by = child_fks.copy()

            schema.relationships[set_name] = Relationship(
                set_name=set_name,
                parent_record=parent_record,
                child_record=child_record,
                cardinality=rel_json.get("cardinality") or "1:N",
                parent_key=parent_key,
                child_fk=child_fk,
                parent_keys=parent_keys,
                child_fks=child_fks,
                order_by=order_by,
            )

    def _parse_field_map(
        self,
        payload: dict,
        schema: SchemaModel,
    ) -> None:
        field_map = payload.get("field_map") or {}

        if not isinstance(field_map, dict):
            return

        parsed: dict[str, dict] = {}

        for key, value in field_map.items():
            normalized_key = self._upper_or_empty(key)

            if not normalized_key:
                continue

            if isinstance(value, dict):
                parsed[normalized_key] = value
            else:
                parsed[normalized_key] = {
                    "host": str(value),
                }

        schema.field_map = parsed

    def _extract_primary_keys(
        self,
        source: dict,
    ) -> list[str]:
        keys: list[str] = []

        raw_primary_keys = source.get("primary_keys")

        if isinstance(raw_primary_keys, list):
            for key in raw_primary_keys:
                normalized = self._upper_or_empty(key)

                if normalized and normalized not in keys:
                    keys.append(normalized)

        elif raw_primary_keys:
            normalized = self._upper_or_empty(raw_primary_keys)

            if normalized and normalized not in keys:
                keys.append(normalized)

        primary_key = self._upper_or_empty(
            source.get("primary_key")
        )

        if primary_key and primary_key not in keys:
            keys.append(primary_key)

        return keys

    def _extract_key_list(
        self,
        source: dict,
        plural_keys: list[str],
        single_keys: list[str],
    ) -> list[str]:
        result: list[str] = []

        for key in plural_keys:
            values = source.get(key)

            if not values:
                continue

            if not isinstance(values, list):
                values = [values]

            for value in values:
                normalized = self._upper_or_empty(value)

                if normalized and normalized not in result:
                    result.append(normalized)

        for key in single_keys:
            value = source.get(key)
            normalized = self._upper_or_empty(value)

            if normalized and normalized not in result:
                result.append(normalized)

        return result

    def _resolve_parent_key(
        self,
        schema: SchemaModel,
        parent_record: str,
    ) -> str | None:
        record = schema.records.get(parent_record)

        if not record:
            return None

        if hasattr(record, "effective_primary_keys"):
            primary_keys = record.effective_primary_keys()

            if primary_keys:
                return primary_keys[0]

        return record.primary_key

    def _resolve_child_fk(
        self,
        schema: SchemaModel,
        parent_record: str,
        child_record: str,
        parent_keys: list[str] | None = None,
    ) -> str | None:
        parent = schema.records.get(parent_record)
        child = schema.records.get(child_record)

        if not parent or not child:
            return None

        keys = parent_keys or []

        if not keys:
            if hasattr(parent, "effective_primary_keys"):
                keys = parent.effective_primary_keys()

            if not keys and parent.primary_key:
                keys = [parent.primary_key]

        for key in keys:
            if key in child.fields:
                return key

        return None

    def _first_non_empty(
        self,
        source: dict,
        keys: list[str],
    ) -> Any:
        for key in keys:
            value = source.get(key)

            if value is None:
                continue

            if isinstance(value, str):
                value = value.strip()

                if not value:
                    continue

            return value

        return None

    def _upper_or_empty(
        self,
        value: Any,
    ) -> str:
        if value is None:
            return ""

        text = str(value).strip()

        if not text:
            return ""

        return text.upper()

    def _upper_or_none(
        self,
        value: str | None,
    ) -> str | None:
        normalized = self._upper_or_empty(value)

        return normalized or None