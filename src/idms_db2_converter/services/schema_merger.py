from copy import deepcopy
import re

from idms_db2_converter.generators.naming import Naming
from idms_db2_converter.models import Relationship, SchemaModel


class SchemaMerger:
    """
    Merge DB2 DDL schema with IDMS schema listing.

    Rules:
    - DDL wins for physical column definitions.
    - IDMS wins for legacy field names, IDMS set names, and field_map.
    """

    def merge_physical_with_idms(
        self,
        physical_schema: SchemaModel,
        idms_schema: SchemaModel,
    ) -> SchemaModel:
        merged = deepcopy(physical_schema)

        if not getattr(merged, "schema_source", None):
            merged.schema_source = "DDL"

        merged.schema_source = f"{merged.schema_source}+IDMS_SCHEMA"

        self._build_record_table_map(merged, idms_schema)
        self._build_field_map_from_idms_to_physical(merged, idms_schema)
        self._build_date_part_map_from_idms_to_physical(merged, idms_schema)
        self._preserve_idms_set_names(merged, idms_schema)
        self._merge_validation_messages(merged, idms_schema)

        return merged

    def _build_record_table_map(
        self,
        merged: SchemaModel,
        idms_schema: SchemaModel,
    ) -> None:
        for idms_record_name in idms_schema.records:
            physical_record_name = self._find_matching_record(
                schema=merged,
                record_name=idms_record_name,
            )

            if physical_record_name:
                merged.record_table_map[idms_record_name] = physical_record_name
            else:
                merged.record_table_map[idms_record_name] = self._table_name(
                    idms_record_name
                )

    def _build_field_map_from_idms_to_physical(
        self,
        merged: SchemaModel,
        idms_schema: SchemaModel,
    ) -> None:
        for idms_record_name in idms_schema.records:
            physical_record_name = merged.record_table_map.get(idms_record_name)

            if not physical_record_name:
                continue

            if physical_record_name not in merged.records:
                continue

            physical_record = merged.records[physical_record_name]

            for idms_field_name, meta in idms_schema.field_map.items():
                idms_host = str(meta.get("host", "")).upper()

                if not self._host_belongs_to_record(idms_host, idms_record_name):
                    continue

                normalized_idms_field = self._normalize_field_name(idms_field_name)

                physical_column = self._find_physical_column(
                    physical_record=physical_record,
                    normalized_idms_field=normalized_idms_field,
                    idms_host=idms_host,
                    idms_record_name=idms_record_name,
                )

                if not physical_column:
                    continue

                merged.field_map[idms_field_name.upper()] = {
                    "host": Naming.hv(idms_record_name, physical_column)
                }

    def _build_date_part_map_from_idms_to_physical(
        self,
        merged: SchemaModel,
        idms_schema: SchemaModel,
    ) -> None:
        for idms_field_name, meta in idms_schema.date_part_map.items():
            idms_host = str(meta.get("host", "")).upper()

            idms_record_name = self._find_record_for_host(
                host=idms_host,
                record_names=list(idms_schema.records.keys()),
            )

            if not idms_record_name:
                continue

            physical_record_name = merged.record_table_map.get(idms_record_name)

            if not physical_record_name:
                continue

            if physical_record_name not in merged.records:
                continue

            physical_record = merged.records[physical_record_name]

            idms_column = self._column_from_host(idms_host, idms_record_name)

            if not idms_column:
                continue

            physical_column = self._find_physical_column(
                physical_record=physical_record,
                normalized_idms_field=idms_column,
                idms_host=idms_host,
                idms_record_name=idms_record_name,
            )

            if not physical_column:
                continue

            column = physical_record.fields[physical_column]

            substring_start = meta.get("substring_start")
            substring_length = meta.get("substring_length")

            if column.datatype.upper() == "DATE":
                part = self._date_part_name(idms_field_name)

                if part == "YEAR":
                    substring_start = 3
                    substring_length = 2
                elif part == "MONTH":
                    substring_start = 6
                    substring_length = 2
                elif part == "DAY":
                    substring_start = 9
                    substring_length = 2

            merged.date_part_map[idms_field_name.upper()] = {
                "host": Naming.hv(idms_record_name, physical_column),
                "substring_start": substring_start,
                "substring_length": substring_length,
            }

    def _preserve_idms_set_names(
        self,
        merged: SchemaModel,
        idms_schema: SchemaModel,
    ) -> None:
        for set_name, idms_rel in idms_schema.relationships.items():
            idms_parent = idms_rel.parent_record
            idms_child = idms_rel.child_record

            physical_parent = merged.record_table_map.get(idms_parent)
            physical_child = merged.record_table_map.get(idms_child)

            if not physical_parent or not physical_child:
                continue

            ddl_rel = self._find_relationship_by_records(
                schema=merged,
                parent_record=physical_parent,
                child_record=physical_child,
            )

            if ddl_rel:
                parent_key = ddl_rel.parent_key
                child_fk = ddl_rel.child_fk
                order_by = ddl_rel.order_by
            else:
                parent_key = self._find_matching_column_name(
                    record=merged.records[physical_parent],
                    name=idms_rel.parent_key or "",
                )

                child_fk = self._find_matching_column_name(
                    record=merged.records[physical_child],
                    name=idms_rel.child_fk or idms_rel.parent_key or "",
                )

                order_by = [child_fk] if child_fk else []

            if not parent_key or not child_fk:
                continue

            merged.relationships[set_name] = Relationship(
                set_name=set_name,
                parent_record=idms_parent,
                child_record=idms_child,
                cardinality=idms_rel.cardinality or "1:N",
                parent_key=parent_key,
                child_fk=child_fk,
                order_by=order_by or [child_fk],
            )

    def _find_physical_column(
        self,
        physical_record,
        normalized_idms_field: str,
        idms_host: str,
        idms_record_name: str,
    ) -> str | None:
        direct = self._find_matching_column_name(
            record=physical_record,
            name=normalized_idms_field,
        )

        if direct:
            return direct

        from_host = self._column_from_host(idms_host, idms_record_name)

        if from_host:
            direct = self._find_matching_column_name(
                record=physical_record,
                name=from_host,
            )

            if direct:
                return direct

        singular = self._singularize(normalized_idms_field)

        if singular != normalized_idms_field:
            direct = self._find_matching_column_name(
                record=physical_record,
                name=singular,
            )

            if direct:
                return direct

        return self._find_flattened_occurs_column(
            physical_record=physical_record,
            name=normalized_idms_field,
        )

    def _find_flattened_occurs_column(
        self,
        physical_record,
        name: str,
    ) -> str | None:
        candidates = [
            column_name
            for column_name in physical_record.fields
            if column_name.upper().startswith(name.upper() + "_")
        ]

        if not candidates:
            singular = self._singularize(name)
            candidates = [
                column_name
                for column_name in physical_record.fields
                if column_name.upper().startswith(singular.upper() + "_")
            ]

        if not candidates:
            return None

        return sorted(candidates)[0]

    def _find_matching_record(
        self,
        schema: SchemaModel,
        record_name: str,
    ) -> str | None:
        record_name = record_name.upper()

        if record_name in schema.records:
            return record_name

        normalized = self._normalize_record_name(record_name)

        for candidate in schema.records:
            if self._normalize_record_name(candidate) == normalized:
                return candidate

        return None

    def _find_matching_column_name(
        self,
        record,
        name: str,
    ) -> str | None:
        normalized = self._normalize_field_name(name)

        if normalized in record.fields:
            return normalized

        for column_name in record.fields:
            if column_name.upper() == normalized:
                return column_name

        return None

    def _find_relationship_by_records(
        self,
        schema: SchemaModel,
        parent_record: str,
        child_record: str,
    ) -> Relationship | None:
        normalized_parent = self._normalize_record_name(parent_record)
        normalized_child = self._normalize_record_name(child_record)

        for relationship in schema.relationships.values():
            if (
                self._normalize_record_name(relationship.parent_record)
                == normalized_parent
                and self._normalize_record_name(relationship.child_record)
                == normalized_child
            ):
                return relationship

        return None

    def _host_belongs_to_record(
        self,
        host: str,
        record_name: str,
    ) -> bool:
        normalized_host = self._normalize_token(host)
        normalized_record = self._normalize_token(record_name)

        return normalized_host.startswith(f"HV_{normalized_record}_")

    def _find_record_for_host(
        self,
        host: str,
        record_names: list[str],
    ) -> str | None:
        normalized_host = self._normalize_token(host)

        for record_name in sorted(record_names, key=len, reverse=True):
            normalized_record = self._normalize_token(record_name)

            if normalized_host.startswith(f"HV_{normalized_record}_"):
                return record_name

        return None

    def _column_from_host(
        self,
        host: str,
        record_name: str,
    ) -> str | None:
        normalized_host = self._normalize_token(host)
        normalized_record = self._normalize_token(record_name)

        prefix = f"HV_{normalized_record}_"

        if not normalized_host.startswith(prefix):
            return None

        return normalized_host[len(prefix):].upper()

    def _date_part_name(
        self,
        idms_field_name: str,
    ) -> str | None:
        normalized = self._normalize_field_name(idms_field_name)

        if normalized.endswith("_YEAR"):
            return "YEAR"

        if normalized.endswith("_MONTH"):
            return "MONTH"

        if normalized.endswith("_DAY"):
            return "DAY"

        return None

    def _normalize_token(
        self,
        value: str,
    ) -> str:
        return value.upper().replace("-", "_")

    def _normalize_record_name(
        self,
        value: str,
    ) -> str:
        return value.upper().replace("-", "_")

    def _normalize_field_name(
        self,
        value: str,
    ) -> str:
        value = value.upper()
        value = re.sub(r"-\d{4}$", "", value)
        return value.replace("-", "_")

    def _singularize(
        self,
        value: str,
    ) -> str:
        value = value.upper()

        if value.endswith("IES"):
            return value[:-3] + "Y"

        if value.endswith("S"):
            return value[:-1]

        return value

    def _table_name(
        self,
        record_name: str,
    ) -> str:
        return record_name.upper().replace("-", "_")

    def _merge_validation_messages(
        self,
        merged: SchemaModel,
        overlay: SchemaModel,
    ) -> None:
        if hasattr(merged, "validation_messages") and hasattr(
            overlay,
            "validation_messages",
        ):
            merged.validation_messages.extend(overlay.validation_messages)