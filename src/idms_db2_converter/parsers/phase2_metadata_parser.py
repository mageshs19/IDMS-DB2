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

    Generic behavior only:
    - No hardcoded DB2 table names.
    - No hardcoded DB2 column names.
    - No hardcoded business record names.
    - Uses only names present in payload:
      records, fields, relationships, table_key_map, field_map, etc.

    Supports:
    - records / tables / db2_tables
    - primary_key and primary_keys
    - relationships / sets / db2_relationships
    - parent_key / parent_keys
    - child_fk / child_fks
    - record_table_map
    - field_map
    - calc_key_map
    - table_key_map
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
        text: str,
    ) -> SchemaModel:
        schema = SchemaModel()

        if not text or not text.strip():
            return schema

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConversionError(
                f"Invalid Phase 2 metadata JSON: {exc}"
            ) from exc

        if not isinstance(payload, dict):
            raise ConversionError(
                "Invalid Phase 2 metadata JSON: root must be an object."
            )

        self._parse_records(
            payload=payload,
            schema=schema,
        )

        self._merge_table_key_map(
            payload=payload,
            schema=schema,
        )

        self._parse_relationships(
            payload=payload,
            schema=schema,
        )

        self._merge_record_table_map(
            payload=payload,
            schema=schema,
        )

        self._merge_field_map(
            payload=payload,
            schema=schema,
        )

        self._merge_calc_key_map(
            payload=payload,
            schema=schema,
        )

        self._merge_table_key_map_to_schema(
            payload=payload,
            schema=schema,
        )

        self._merge_set_ordering_map(
            payload=payload,
            schema=schema,
        )

        self._merge_navigation_intent(
            payload=payload,
            schema=schema,
        )

        self._merge_nullable_fk_map(
            payload=payload,
            schema=schema,
        )

        self._merge_date_part_map(
            payload=payload,
            schema=schema,
        )

        self._merge_output_semantics(
            payload=payload,
            schema=schema,
        )

        self._merge_paragraph_operation_graph(
            payload=payload,
            schema=schema,
        )

        self._merge_validation_messages(
            payload=payload,
            schema=schema,
        )

        self._apply_key_flags(
            schema=schema,
        )

        schema.schema_source = "PHASE2_METADATA"

        return schema

    def _parse_records(
        self,
        payload: dict,
        schema: SchemaModel,
    ) -> None:
        record_items = (
            payload.get("records")
            or payload.get("tables")
            or payload.get("db2_tables")
            or []
        )

        if isinstance(record_items, dict):
            record_items = list(record_items.values())

        for record_json in record_items:
            if not isinstance(record_json, dict):
                continue

            record_name = self.normalize_name(
                self._get_first_non_empty(
                    source=record_json,
                    keys=[
                        "name",
                        "record",
                        "table",
                        "table_name",
                        "record_name",
                    ],
                )
            )

            if not record_name:
                continue

            primary_keys = self._extract_primary_keys(
                source=record_json,
            )

            fields = self._parse_fields(
                record_json=record_json,
                primary_keys=primary_keys,
            )

            primary_key = primary_keys[0] if primary_keys else None

            record = Record(
                name=record_name,
                primary_key=primary_key,
                primary_keys=primary_keys,
                fields=fields,
            )

            record.set_primary_keys(
                keys=primary_keys,
            )

            schema.records[record_name] = record

    def _parse_fields(
        self,
        record_json: dict,
        primary_keys: list[str],
    ) -> dict[str, Column]:
        fields: dict[str, Column] = {}

        field_items = (
            record_json.get("fields")
            or record_json.get("columns")
            or []
        )

        if isinstance(field_items, dict):
            field_items = list(field_items.values())

        primary_key_set = {
            self.normalize_name(primary_key)
            for primary_key in primary_keys
            if primary_key
        }

        for field_json in field_items:
            if not isinstance(field_json, dict):
                continue

            field_name = self.normalize_name(
                self._get_first_non_empty(
                    source=field_json,
                    keys=[
                        "name",
                        "field",
                        "column",
                        "column_name",
                    ],
                )
            )

            if not field_name:
                continue

            datatype = (
                self._get_first_non_empty(
                    source=field_json,
                    keys=[
                        "datatype",
                        "data_type",
                        "type",
                    ],
                )
                or "CHAR"
            )

            datatype = str(datatype).upper()

            nullable = field_json.get("nullable")

            if nullable is None:
                nullable = field_name not in primary_key_set

            primary_key_flag = bool(
                field_json.get("primary_key", False)
                or field_name in primary_key_set
            )

            fields[field_name] = Column(
                name=field_name,
                datatype=datatype,
                length=self._safe_int_or_none(
                    field_json.get("length"),
                ),
                scale=self._safe_int_or_none(
                    field_json.get("scale"),
                ),
                nullable=bool(nullable) if not primary_key_flag else False,
                primary_key=primary_key_flag,
                generated=bool(field_json.get("generated", False)),
                source_kind=str(field_json.get("source_kind", "") or ""),
            )

        return fields

    def _parse_relationships(
        self,
        payload: dict,
        schema: SchemaModel,
    ) -> None:
        relationship_items = (
            payload.get("relationships")
            or payload.get("sets")
            or payload.get("db2_relationships")
            or []
        )

        if isinstance(relationship_items, dict):
            relationship_items = list(relationship_items.values())

        for rel_json in relationship_items:
            if not isinstance(rel_json, dict):
                continue

            set_name = self.normalize_name(
                self._get_first_non_empty(
                    source=rel_json,
                    keys=[
                        "set_name",
                        "name",
                        "set",
                    ],
                )
            )

            parent_record = self.normalize_name(
                self._get_first_non_empty(
                    source=rel_json,
                    keys=[
                        "parent_record",
                        "owner_record",
                        "parent",
                        "owner",
                        "parent_table",
                    ],
                )
            )

            child_record = self.normalize_name(
                self._get_first_non_empty(
                    source=rel_json,
                    keys=[
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
                ],
            )

            if not parent_keys:
                parent_key = self._resolve_parent_key(
                    schema=schema,
                    parent_record=parent_record,
                )

                if parent_key:
                    parent_keys = [parent_key]

            if not child_fks:
                child_fk = self._resolve_child_fk(
                    schema=schema,
                    parent_record=parent_record,
                    child_record=child_record,
                    parent_keys=parent_keys,
                )

                if child_fk:
                    child_fks = [child_fk]

            order_by = [
                self.normalize_name(value)
                for value in rel_json.get("order_by", []) or []
                if value
            ]

            if not order_by and child_fks:
                order_by = child_fks.copy()

            parent_key_single = parent_keys[0] if parent_keys else None
            child_fk_single = child_fks[0] if child_fks else None

            schema.relationships[set_name] = Relationship(
                set_name=set_name,
                parent_record=parent_record,
                child_record=child_record,
                cardinality=rel_json.get("cardinality") or "1:N",
                parent_key=parent_key_single,
                child_fk=child_fk_single,
                parent_keys=parent_keys,
                child_fks=child_fks,
                order_by=order_by,
            )

    def _merge_table_key_map(
        self,
        payload: dict,
        schema: SchemaModel,
    ) -> None:
        table_key_map = payload.get("table_key_map") or {}

        if not isinstance(table_key_map, dict):
            return

        for table_name_raw, key_payload in table_key_map.items():
            table_name = self.normalize_name(table_name_raw)

            if not table_name:
                continue

            if not isinstance(key_payload, dict):
                continue

            primary_keys = self._extract_key_list(
                source=key_payload,
                plural_keys=[
                    "primary_keys",
                    "pk_columns",
                ],
                single_keys=[
                    "primary_key",
                    "pk",
                ],
            )

            if not primary_keys:
                continue

            record = schema.records.get(table_name)

            if record is None:
                continue

            record.set_primary_keys(
                keys=primary_keys,
            )

    def _merge_table_key_map_to_schema(
        self,
        payload: dict,
        schema: SchemaModel,
    ) -> None:
        table_key_map = payload.get("table_key_map") or {}

        if not isinstance(table_key_map, dict):
            return

        schema.table_key_map = {}

        for table_name, value in table_key_map.items():
            normalized_table_name = self.normalize_name(table_name)

            if not normalized_table_name:
                continue

            if isinstance(value, dict):
                schema.table_key_map[normalized_table_name] = self._normalize_nested(
                    value=value,
                )
            else:
                schema.table_key_map[normalized_table_name] = value

    def _merge_record_table_map(
        self,
        payload: dict,
        schema: SchemaModel,
    ) -> None:
        for key, value in (payload.get("record_table_map") or {}).items():
            schema.record_table_map[self.normalize_name(key)] = self.normalize_name(value)

    def _merge_field_map(
        self,
        payload: dict,
        schema: SchemaModel,
    ) -> None:
        for key, value in (payload.get("field_map") or {}).items():
            schema.field_map[self.normalize_name(key)] = value

    def _merge_calc_key_map(
        self,
        payload: dict,
        schema: SchemaModel,
    ) -> None:
        for key, value in (payload.get("calc_key_map") or {}).items():
            schema.calc_key_map[self.normalize_name(key)] = value

    def _merge_set_ordering_map(
        self,
        payload: dict,
        schema: SchemaModel,
    ) -> None:
        for key, value in (payload.get("set_ordering_map") or {}).items():
            schema.set_ordering_map[self.normalize_name(key)] = value

            relationship = schema.relationships.get(
                self.normalize_name(key),
            )

            if relationship is None:
                continue

            if isinstance(value, dict):
                parent_keys = self._extract_key_list(
                    source=value,
                    plural_keys=[
                        "parent_keys",
                    ],
                    single_keys=[
                        "parent_key",
                    ],
                )

                child_fks = self._extract_key_list(
                    source=value,
                    plural_keys=[
                        "child_fks",
                    ],
                    single_keys=[
                        "child_fk",
                    ],
                )

                if parent_keys:
                    relationship.parent_keys = parent_keys
                    relationship.parent_key = parent_keys[0]

                if child_fks:
                    relationship.child_fks = child_fks
                    relationship.child_fk = child_fks[0]

                order_by = value.get("order_by") or []

                if order_by:
                    relationship.order_by = [
                        self.normalize_name(item)
                        for item in order_by
                        if item
                    ]

    def _merge_navigation_intent(
        self,
        payload: dict,
        schema: SchemaModel,
    ) -> None:
        value = payload.get("navigation_intent") or {}

        if isinstance(value, dict):
            schema.navigation_intent = value

    def _merge_nullable_fk_map(
        self,
        payload: dict,
        schema: SchemaModel,
    ) -> None:
        value = payload.get("nullable_fk_map") or {}

        if isinstance(value, dict):
            schema.nullable_fk_map = value

    def _merge_date_part_map(
        self,
        payload: dict,
        schema: SchemaModel,
    ) -> None:
        value = payload.get("date_part_map") or {}

        if isinstance(value, dict):
            schema.date_part_map = {
                self.normalize_name(key): item
                for key, item in value.items()
            }

    def _merge_output_semantics(
        self,
        payload: dict,
        schema: SchemaModel,
    ) -> None:
        value = payload.get("output_semantics") or {}

        if isinstance(value, dict):
            schema.output_semantics = value

    def _merge_paragraph_operation_graph(
        self,
        payload: dict,
        schema: SchemaModel,
    ) -> None:
        value = payload.get("paragraph_operation_graph") or {}

        if isinstance(value, dict):
            schema.paragraph_operation_graph = value

    def _merge_validation_messages(
        self,
        payload: dict,
        schema: SchemaModel,
    ) -> None:
        messages = payload.get("validation_messages") or []

        if isinstance(messages, list):
            schema.validation_messages.extend(
                str(message)
                for message in messages
            )

    def _apply_key_flags(
        self,
        schema: SchemaModel,
    ) -> None:
        for record in schema.records.values():
            primary_keys = record.effective_primary_keys()

            for primary_key in primary_keys:
                if primary_key not in record.fields:
                    continue

                record.fields[primary_key].primary_key = True
                record.fields[primary_key].nullable = False

            if not record.primary_key and primary_keys:
                record.primary_key = primary_keys[0]

    def _resolve_parent_key(
        self,
        schema: SchemaModel,
        parent_record: str,
    ) -> str | None:
        record = schema.records.get(parent_record)

        if not record:
            return None

        primary_keys = record.effective_primary_keys()

        if primary_keys:
            return primary_keys[0]

        return record.primary_key

    def _resolve_child_fk(
        self,
        schema: SchemaModel,
        parent_record: str,
        child_record: str,
        parent_keys: list[str],
    ) -> str | None:
        child = schema.records.get(child_record)

        if not child:
            return None

        for parent_key in parent_keys or []:
            if parent_key in child.fields:
                return parent_key

        parent = schema.records.get(parent_record)

        if parent is None:
            return None

        parent_effective_keys = parent.effective_primary_keys()

        for parent_key in parent_effective_keys:
            if parent_key in child.fields:
                return parent_key

        parent_base_keys = {
            self.remove_record_suffix(parent_key): parent_key
            for parent_key in parent_effective_keys
            if parent_key
        }

        for child_field_name in child.fields:
            child_base_name = self.remove_record_suffix(child_field_name)

            if child_base_name in parent_base_keys:
                return child_field_name

        return None

    def _extract_primary_keys(
        self,
        source: dict,
    ) -> list[str]:
        return self._extract_key_list(
            source=source,
            plural_keys=[
                "primary_keys",
                "pk_columns",
            ],
            single_keys=[
                "primary_key",
                "pk",
            ],
        )

    def _extract_key_list(
        self,
        source: dict,
        plural_keys: list[str],
        single_keys: list[str],
    ) -> list[str]:
        values: list[str] = []

        for key in plural_keys:
            raw_value = source.get(key)

            if raw_value is None:
                continue

            if isinstance(raw_value, list):
                for item in raw_value:
                    normalized = self.normalize_name(item)

                    if normalized and normalized not in values:
                        values.append(normalized)

            elif isinstance(raw_value, str):
                normalized = self.normalize_name(raw_value)

                if normalized and normalized not in values:
                    values.append(normalized)

        for key in single_keys:
            raw_value = source.get(key)

            if raw_value is None:
                continue

            normalized = self.normalize_name(raw_value)

            if normalized and normalized not in values:
                values.append(normalized)

        return values

    def _get_first_non_empty(
        self,
        source: dict,
        keys: list[str],
    ) -> str | None:
        for key in keys:
            value = source.get(key)

            if value is None:
                continue

            if isinstance(value, str):
                if value.strip():
                    return value

            else:
                return str(value)

        return None

    def _normalize_nested(
        self,
        value,
    ):
        if isinstance(value, dict):
            return {
                self.normalize_name(key): self._normalize_nested(item)
                for key, item in value.items()
            }

        if isinstance(value, list):
            return [
                self._normalize_nested(item)
                for item in value
            ]

        if isinstance(value, str):
            return self.normalize_name(value)

        return value

    def _safe_int_or_none(
        self,
        value,
    ) -> int | None:
        try:
            if value is None:
                return None

            return int(value)
        except Exception:
            return None

    def normalize_name(
        self,
        value,
    ) -> str:
        if value is None:
            return ""

        text = str(value).strip().upper()

        if not text:
            return ""

        text = text.replace("-", "_")
        text = text.replace(" ", "_")

        while "__" in text:
            text = text.replace("__", "_")

        return text.strip("_")

    def remove_record_suffix(
        self,
        value: str,
    ) -> str:
        text = self.normalize_name(value)

        if not text:
            return ""

        parts = text.rsplit("_", 1)

        if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 4:
            return parts[0]

        return text