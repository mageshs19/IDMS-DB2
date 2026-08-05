import json
import re

from typing import Any

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

    Critical rule:
    - If an existing DDL schema is passed into parse_into_schema(), DDL physical
      columns must win for datatype, length, scale, nullable, and generated flags.
    - Phase 2 metadata enriches maps and relationships but must not downgrade
      physical DDL metadata.

    This prevents host variables such as:
    - PIC X(1) instead of PIC X(45)
    - PIC S9(18) COMP-3 instead of PIC S9(4) COMP
    """

    DEFAULT_DATATYPE = "CHAR"

    def parse_as_schema(
        self,
        text: str | None,
    ) -> SchemaModel:
        schema = SchemaModel()

        return self.parse_into_schema(
            text=text,
            schema=schema,
        )

    def parse_into_schema(
        self,
        text: str | None,
        schema: SchemaModel,
    ) -> SchemaModel:
        if schema is None:
            schema = SchemaModel()

        if not text or not str(text).strip():
            return schema

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConversionError(f"Invalid Phase 2 metadata JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise ConversionError("Invalid Phase 2 metadata JSON: root must be an object.")

        preserve_existing_physical = self._has_existing_physical_schema(
            schema=schema,
        )

        self._parse_records(
            payload=payload,
            schema=schema,
            preserve_existing_physical=preserve_existing_physical,
        )

        self._merge_record_table_map(
            payload=payload,
            schema=schema,
        )

        self._parse_field_map(
            payload=payload,
            schema=schema,
        )

        self._merge_calc_key_map(
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

        if preserve_existing_physical:
            schema.schema_source = "DDL+PHASE2_METADATA"
        else:
            schema.schema_source = "PHASE2_METADATA"

        return schema

    def _has_existing_physical_schema(
        self,
        schema: SchemaModel,
    ) -> bool:
        for record in getattr(schema, "records", {}).values():
            if getattr(record, "fields", None):
                return True

        return False

    def _parse_records(
        self,
        payload: dict,
        schema: SchemaModel,
        preserve_existing_physical: bool,
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

            if record_name in schema.records:
                existing_record = schema.records[record_name]

                if primary_keys:
                    self._set_record_primary_keys(
                        record=existing_record,
                        primary_keys=primary_keys,
                    )
                elif primary_key and not existing_record.primary_key:
                    existing_record.primary_key = primary_key

                for field_name, metadata_field in fields.items():
                    if field_name in existing_record.fields:
                        if preserve_existing_physical:
                            self._merge_non_physical_column_flags(
                                existing_column=existing_record.fields[field_name],
                                metadata_column=metadata_field,
                            )
                        else:
                            existing_record.fields[field_name] = metadata_field
                    else:
                        existing_record.fields[field_name] = metadata_field

            else:
                record = Record(
                    name=record_name,
                    primary_key=primary_key,
                    primary_keys=primary_keys,
                    fields=fields,
                )

                self._set_record_primary_keys(
                    record=record,
                    primary_keys=primary_keys,
                )

                schema.records[record_name] = record

    def _parse_fields(
        self,
        record_json: dict,
        primary_keys: list[str],
    ) -> dict[str, Column]:
        field_items = (
            record_json.get("fields")
            or record_json.get("columns")
            or record_json.get("db2_columns")
            or []
        )

        if isinstance(field_items, dict):
            field_items = list(field_items.values())

        fields: dict[str, Column] = {}

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

            datatype, length, scale = self._parse_metadata_datatype(
                field_json=field_json,
            )

            if not datatype:
                datatype = self.DEFAULT_DATATYPE

            nullable = field_json.get("nullable")

            if nullable is None:
                nullable = field_name not in primary_keys

            primary_key_flag = (
                bool(field_json.get("primary_key", False))
                or field_name in primary_keys
            )

            if primary_key_flag:
                nullable = False

            fields[field_name] = Column(
                name=field_name,
                datatype=datatype,
                length=length,
                scale=scale,
                nullable=bool(nullable),
                primary_key=primary_key_flag,
                generated=bool(field_json.get("generated", False)),
                source_kind=str(field_json.get("source_kind", "") or ""),
            )

        return fields

    def _parse_metadata_datatype(
        self,
        field_json: dict,
    ) -> tuple[str, int | None, int | None]:
        raw_datatype = self._get_first_non_empty(
            source=field_json,
            keys=[
                "datatype",
                "data_type",
                "type",
                "db2_datatype",
            ],
        )

        datatype_text = self.normalize_datatype(
            raw_datatype,
        )

        length = self._safe_int_or_none(
            field_json.get("length"),
        )

        scale = self._safe_int_or_none(
            field_json.get("scale"),
        )

        if not datatype_text:
            return "", length, scale

        decimal_match = re.match(
            r"^(DECIMAL|NUMERIC|DEC)\s*$\s*(\d+)\s*(?:,\s*(\d+)\s*)?$$",
            datatype_text,
        )

        if decimal_match:
            return (
                "DECIMAL",
                int(decimal_match.group(2)),
                int(decimal_match.group(3) or 0),
            )

        char_match = re.match(
            r"^(VARCHAR|CHAR|CHARACTER|LONG VARCHAR)\s*$\s*(\d+)\s*$$",
            datatype_text,
        )

        if char_match:
            datatype_name = char_match.group(1)

            if datatype_name == "CHARACTER":
                datatype_name = "CHAR"

            return (
                datatype_name,
                int(char_match.group(2)),
                scale,
            )

        if datatype_text == "VARCHAR":
            return "VARCHAR", length, scale

        if datatype_text == "LONG VARCHAR":
            return "LONG VARCHAR", length, scale

        if datatype_text in {"CHAR", "CHARACTER"}:
            return "CHAR", length, scale

        if datatype_text in {"DECIMAL", "NUMERIC", "DEC"}:
            return "DECIMAL", length, scale

        if datatype_text in {"INTEGER", "INT"}:
            return "INTEGER", 9, 0

        if datatype_text == "SMALLINT":
            return "SMALLINT", 4, 0

        if datatype_text == "BIGINT":
            return "BIGINT", 18, 0

        if datatype_text == "DATE":
            return "DATE", None, None

        if datatype_text == "TIME":
            return "TIME", None, None

        if datatype_text == "TIMESTAMP":
            return "TIMESTAMP", None, None

        return datatype_text, length, scale

    def _merge_non_physical_column_flags(
        self,
        existing_column: Column,
        metadata_column: Column,
    ) -> None:
        if getattr(metadata_column, "primary_key", False):
            existing_column.primary_key = True
            existing_column.nullable = False

        if getattr(metadata_column, "generated", False):
            existing_column.generated = True

        if getattr(metadata_column, "source_kind", ""):
            existing_column.source_kind = metadata_column.source_kind

    def _set_record_primary_keys(
        self,
        record,
        primary_keys: list[str],
    ) -> None:
        cleaned: list[str] = []

        for key in primary_keys or []:
            normalized = self.normalize_name(key)

            if not normalized:
                continue

            if normalized in cleaned:
                continue

            cleaned.append(normalized)

        if hasattr(record, "set_primary_keys"):
            record.set_primary_keys(
                keys=cleaned,
            )
        else:
            record.primary_keys = cleaned
            record.primary_key = cleaned[0] if cleaned else None

        for key in cleaned:
            if key in record.fields:
                record.fields[key].primary_key = True
                record.fields[key].nullable = False

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
                        "relationship",
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
                if self.normalize_name(value)
            ]

            if not order_by and child_fks:
                order_by = child_fks.copy()

            parent_key_single = parent_keys[0] if parent_keys else None
            child_fk_single = child_fks[0] if child_fks else None

            if set_name in schema.relationships:
                rel = schema.relationships[set_name]
                rel.parent_record = parent_record or rel.parent_record
                rel.child_record = child_record or rel.child_record
                rel.parent_key = parent_key_single or rel.parent_key
                rel.child_fk = child_fk_single or rel.child_fk
                rel.parent_keys = parent_keys or getattr(rel, "parent_keys", [])
                rel.child_fks = child_fks or getattr(rel, "child_fks", [])
                rel.order_by = order_by or rel.order_by
                rel.cardinality = rel_json.get("cardinality") or rel.cardinality or "1:N"
                continue

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

    def _parse_field_map(
        self,
        payload: dict,
        schema: SchemaModel,
    ) -> None:
        value = payload.get("field_map") or {}

        if not isinstance(value, dict):
            return

        for key, item in value.items():
            if isinstance(item, dict):
                parsed_item = item
            else:
                parsed_item = {
                    "host": str(item),
                }

            aliases = self._lookup_aliases(key)

            if isinstance(parsed_item, dict):
                aliases.extend(self._lookup_aliases(parsed_item.get("legacy_field")))
                aliases.extend(self._lookup_aliases(parsed_item.get("column")))

            for alias in self._unique_values(aliases):
                if not alias:
                    continue

                schema.field_map[alias] = parsed_item

    def _merge_record_table_map(
        self,
        payload: dict,
        schema: SchemaModel,
    ) -> None:
        value = payload.get("record_table_map") or {}

        if not isinstance(value, dict):
            return

        for key, item in value.items():
            normalized_key = self.normalize_name(key)
            normalized_value = self.normalize_name(item)

            if not normalized_key or not normalized_value:
                continue

            schema.record_table_map[normalized_key] = normalized_value

            hyphen_key = self.normalize_cobol_name(key)

            if hyphen_key:
                schema.record_table_map.setdefault(
                    hyphen_key,
                    normalized_value,
                )

    def _merge_calc_key_map(
        self,
        payload: dict,
        schema: SchemaModel,
    ) -> None:
        value = payload.get("calc_key_map") or {}

        if not isinstance(value, dict):
            return

        for key, item in value.items():
            normalized_key = self.normalize_name(key)

            if normalized_key:
                schema.calc_key_map[normalized_key] = item

            hyphen_key = self.normalize_cobol_name(key)

            if hyphen_key:
                schema.calc_key_map.setdefault(
                    hyphen_key,
                    item,
                )

    def _merge_table_key_map(
        self,
        payload: dict,
        schema: SchemaModel,
    ) -> None:
        value = payload.get("table_key_map") or {}

        if not isinstance(value, dict):
            return

        for key, item in value.items():
            normalized_key = self.normalize_name(key)

            if normalized_key:
                schema.table_key_map[normalized_key] = item

            hyphen_key = self.normalize_cobol_name(key)

            if hyphen_key:
                schema.table_key_map.setdefault(
                    hyphen_key,
                    item,
                )

    def _merge_set_ordering_map(
        self,
        payload: dict,
        schema: SchemaModel,
    ) -> None:
        value = payload.get("set_ordering_map") or {}

        if not isinstance(value, dict):
            return

        for key, item in value.items():
            normalized_key = self.normalize_name(key)

            if normalized_key:
                schema.set_ordering_map[normalized_key] = item

            relationship = schema.relationships.get(normalized_key)

            if relationship is None:
                continue

            if isinstance(item, dict):
                parent_keys = self._extract_key_list(
                    source=item,
                    plural_keys=["parent_keys"],
                    single_keys=["parent_key"],
                )

                child_fks = self._extract_key_list(
                    source=item,
                    plural_keys=["child_fks"],
                    single_keys=["child_fk"],
                )

                if parent_keys:
                    relationship.parent_keys = parent_keys
                    relationship.parent_key = parent_keys[0]

                if child_fks:
                    relationship.child_fks = child_fks
                    relationship.child_fk = child_fks[0]

                order_by = item.get("order_by") or []

                if order_by:
                    relationship.order_by = [
                        self.normalize_name(order_item)
                        for order_item in order_by
                        if order_item
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

        if not isinstance(value, dict):
            return

        for key, item in value.items():
            aliases = self._lookup_aliases(key)

            if isinstance(item, dict):
                aliases.extend(self._lookup_aliases(item.get("column")))
                aliases.extend(self._lookup_aliases(item.get("legacy_field")))

            for alias in self._unique_values(aliases):
                if alias:
                    schema.date_part_map[alias] = item

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

        if not isinstance(messages, list):
            return

        schema.validation_messages.extend(str(message) for message in messages)

    def _apply_key_flags(
        self,
        schema: SchemaModel,
    ) -> None:
        for record in schema.records.values():
            primary_keys = []

            if hasattr(record, "effective_primary_keys"):
                primary_keys = record.effective_primary_keys()

            if not primary_keys:
                primary_keys = list(getattr(record, "primary_keys", []) or [])

            if not primary_keys and getattr(record, "primary_key", None):
                primary_keys = [record.primary_key]

            cleaned_primary_keys = []

            for primary_key in primary_keys:
                normalized_primary_key = self.normalize_name(primary_key)

                if not normalized_primary_key:
                    continue

                if normalized_primary_key not in cleaned_primary_keys:
                    cleaned_primary_keys.append(normalized_primary_key)

                if normalized_primary_key not in record.fields:
                    continue

                record.fields[normalized_primary_key].primary_key = True
                record.fields[normalized_primary_key].nullable = False

            if cleaned_primary_keys:
                record.primary_keys = cleaned_primary_keys
                record.primary_key = cleaned_primary_keys[0]

    def _extract_primary_keys(
        self,
        source: dict,
    ) -> list[str]:
        return self._extract_key_list(
            source=source,
            plural_keys=["primary_keys", "pk_columns"],
            single_keys=["primary_key", "pk"],
        )

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
                normalized = self.normalize_name(value)

                if normalized and normalized not in result:
                    result.append(normalized)

        for key in single_keys:
            value = source.get(key)
            normalized = self.normalize_name(value)

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
        parent_keys: list[str],
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

    def _get_first_non_empty(
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

    def _lookup_aliases(
        self,
        value: Any,
    ) -> list[str]:
        if value is None:
            return []

        original = str(value or "").strip().upper()

        if not original:
            return []

        normalized = self.normalize_name(original)
        cobol = self.normalize_cobol_name(original)
        no_numeric_suffix = self.remove_numeric_suffix(normalized)
        no_numeric_suffix_cobol = self.remove_numeric_suffix(cobol)
        no_generated_suffix = self.remove_generated_suffix(normalized)
        no_generated_suffix_cobol = self.remove_generated_suffix(cobol)
        compact = self.compact_name(no_generated_suffix or no_numeric_suffix or normalized)

        return self._unique_values(
            [
                original,
                normalized,
                cobol,
                no_numeric_suffix,
                no_numeric_suffix_cobol,
                no_generated_suffix,
                no_generated_suffix_cobol,
                compact,
            ]
        )

    def normalize_name(
        self,
        value: Any,
    ) -> str:
        if value is None:
            return ""

        text = str(value).strip().upper()

        if not text:
            return ""

        text = text.replace("-", "_")
        text = text.replace(" ", "_")
        text = text.replace("\u00a0", "_")
        text = text.replace("\t", "_")
        text = self._remove_wrapping_quotes(text)
        text = self._strip_table_qualifier(text)
        text = self._collapse_separator(text, "_")

        return text.strip("_")

    def normalize_cobol_name(
        self,
        value: Any,
    ) -> str:
        if value is None:
            return ""

        text = str(value).strip().upper()

        if not text:
            return ""

        text = text.replace("_", "-")
        text = text.replace(" ", "-")
        text = text.replace("\u00a0", "-")
        text = text.replace("\t", "-")
        text = self._remove_wrapping_quotes(text)
        text = self._strip_table_qualifier(text)
        text = self._collapse_separator(text, "-")

        return text.strip("-")

    def normalize_datatype(
        self,
        value: Any,
    ) -> str:
        if value is None:
            return ""

        text = str(value).strip().upper()

        if not text:
            return ""

        return text

    def remove_numeric_suffix(
        self,
        value: Any,
    ) -> str:
        text = self.normalize_name(value)

        if not text:
            return ""

        text = re.sub(r"_[0-9]{4}$", "", text)
        text = re.sub(r"[0-9]{4}$", "", text)
        text = re.sub(r"[_\-\s]+$", "", text)

        return text

    def remove_generated_suffix(
        self,
        value: Any,
    ) -> str:
        text = self.normalize_name(value)

        if not text:
            return ""

        text = re.sub(r"_479[A-Z0-9]+$", "", text)
        text = re.sub(r"479[A-Z0-9]+$", "", text)
        text = re.sub(r"[_\-\s]+$", "", text)

        return text

    def compact_name(
        self,
        value: Any,
    ) -> str:
        if value is None:
            return ""

        return "".join(char for char in str(value or "").upper() if char.isalnum())

    def _unique_values(
        self,
        values: list[str],
    ) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()

        for value in values:
            normalized = str(value or "").strip().upper()

            if not normalized:
                continue

            if normalized in seen:
                continue

            seen.add(normalized)
            result.append(normalized)

        return result

    def _collapse_separator(
        self,
        value: str,
        separator: str,
    ) -> str:
        if separator == "_":
            value = "".join(char if char.isalnum() else "_" for char in value)

            while "__" in value:
                value = value.replace("__", "_")

            return value

        value = "".join(char if char.isalnum() else "-" for char in value)

        while "--" in value:
            value = value.replace("--", "-")

        return value

    def _remove_wrapping_quotes(
        self,
        value: str,
    ) -> str:
        text = value.strip()

        for quote in ['"', "'", "`", "[", "]"]:
            text = text.strip(quote)

        return text

    def _strip_table_qualifier(
        self,
        value: str,
    ) -> str:
        if "." not in value:
            return value

        return value.split(".")[-1]

    def _safe_int_or_none(
        self,
        value,
    ) -> int | None:
        try:
            if value is None:
                return None

            text = str(value).strip()

            if not text:
                return None

            return int(text)
        except Exception:
            return None