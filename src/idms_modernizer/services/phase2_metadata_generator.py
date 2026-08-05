import json
import re

from datetime import datetime
from typing import Any

from idms_modernizer.domain.canonical_models import CanonicalSchema
from idms_modernizer.domain.db2_models import DB2Model, DB2Table, DB2Column
from idms_modernizer.domain.schema_models import SchemaMetadata


class Phase2MetadataGenerator:
    VERSION = "1.0"

    DATE_PARTS = {
        "YEAR": {
            "substring_start": 3,
            "substring_length": 2,
        },
        "MONTH": {
            "substring_start": 6,
            "substring_length": 2,
        },
        "DAY": {
            "substring_start": 9,
            "substring_length": 2,
        },
    }

    YEAR_PARTS = {
        "YEAR",
        "YR",
        "Y",
        "YY",
        "YYYY",
        "DY",
    }

    MONTH_PARTS = {
        "MONTH",
        "MON",
        "MO",
        "M",
        "MM",
        "DM",
    }

    DAY_PARTS = {
        "DAY",
        "D",
        "DD",
    }

    def generate_json(
        self,
        canonical_schema: CanonicalSchema,
        db2_model: DB2Model,
        metadata: SchemaMetadata,
    ) -> str:
        payload = self.generate_payload(
            canonical_schema=canonical_schema,
            db2_model=db2_model,
            metadata=metadata,
        )

        return json.dumps(
            payload,
            indent=2,
        )

    def generate_payload(
        self,
        canonical_schema: CanonicalSchema,
        db2_model: DB2Model,
        metadata: SchemaMetadata,
    ) -> dict[str, Any]:
        db2_table_lookup = self.build_db2_table_lookup(
            db2_model=db2_model,
        )

        canonical_record_lookup = self.build_canonical_record_lookup(
            canonical_schema=canonical_schema,
        )

        records_payload = self.build_records_payload(
            db2_model=db2_model,
        )

        record_table_map = self.build_record_table_map(
            metadata=metadata,
            db2_table_lookup=db2_table_lookup,
        )

        field_map = self.build_field_map(
            metadata=metadata,
            db2_table_lookup=db2_table_lookup,
            record_table_map=record_table_map,
        )

        calc_key_map = self.build_calc_key_map(
            canonical_schema=canonical_schema,
            metadata=metadata,
            record_table_map=record_table_map,
            db2_table_lookup=db2_table_lookup,
        )

        relationships_payload = self.build_relationships_payload(
            canonical_schema=canonical_schema,
            db2_table_lookup=db2_table_lookup,
        )

        set_ordering_map = self.build_set_ordering_map(
            relationships=relationships_payload,
        )

        nullable_fk_map = self.build_nullable_fk_map(
            db2_model=db2_model,
        )

        table_key_map = self.build_table_key_map(
            db2_model=db2_model,
        )

        date_part_map = self.build_date_part_map(
            metadata=metadata,
            db2_table_lookup=db2_table_lookup,
            record_table_map=record_table_map,
        )

        navigation_intent = self.build_navigation_intent(
            relationships=relationships_payload,
        )

        output_semantics = self.build_output_semantics()

        validation_messages = self.build_validation_messages(
            canonical_schema=canonical_schema,
            db2_model=db2_model,
            metadata=metadata,
            field_map=field_map,
        )

        return {
            "version": self.VERSION,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "records": records_payload,
            "record_table_map": record_table_map,
            "field_map": field_map,
            "calc_key_map": calc_key_map,
            "relationships": relationships_payload,
            "set_ordering_map": set_ordering_map,
            "nullable_fk_map": nullable_fk_map,
            "table_key_map": table_key_map,
            "date_part_map": date_part_map,
            "navigation_intent": navigation_intent,
            "output_semantics": output_semantics,
            "validation_messages": validation_messages,
            "canonical_record_lookup_count": len(canonical_record_lookup),
        }

    def build_records_payload(
        self,
        db2_model: DB2Model,
    ) -> list[dict[str, Any]]:
        records_payload: list[dict[str, Any]] = []

        for table in getattr(db2_model, "tables", []) or []:
            fields_payload: list[dict[str, Any]] = []

            primary_keys = list(getattr(table, "primary_keys", []) or [])

            if not primary_keys and getattr(table, "primary_key", None):
                primary_keys = [table.primary_key]

            normalized_primary_keys = {
                self.to_db2_name(primary_key)
                for primary_key in primary_keys
                if primary_key
            }

            for column in getattr(table, "columns", []) or []:
                datatype, length, scale = self.parse_db2_datatype(
                    getattr(column, "datatype", ""),
                )

                column_name = getattr(column, "name", "") or ""
                normalized_column_name = self.to_db2_name(column_name)

                fields_payload.append(
                    {
                        "name": column_name,
                        "column": column_name,
                        "datatype": datatype,
                        "length": length,
                        "scale": scale,
                        "nullable": getattr(column, "nullable", True),
                        "primary_key": (
                            getattr(column, "primary_key", False)
                            or normalized_column_name in normalized_primary_keys
                        ),
                        "generated": getattr(column, "generated", False),
                        "source_kind": getattr(column, "source_kind", ""),
                    }
                )

            records_payload.append(
                {
                    "name": getattr(table, "name", "") or "",
                    "table": getattr(table, "name", "") or "",
                    "primary_key": primary_keys[0] if primary_keys else None,
                    "primary_keys": primary_keys,
                    "fields": fields_payload,
                }
            )

        return records_payload

    def build_table_key_map(
        self,
        db2_model: DB2Model,
    ) -> dict[str, Any]:
        table_key_map: dict[str, Any] = {}

        for table in getattr(db2_model, "tables", []) or []:
            table_name = self.to_db2_name(
                getattr(table, "name", "") or "",
            )

            if not table_name:
                continue

            primary_keys = list(getattr(table, "primary_keys", []) or [])

            if not primary_keys and getattr(table, "primary_key", None):
                primary_keys = [table.primary_key]

            foreign_keys = []

            for foreign_key in getattr(table, "foreign_keys", []) or []:
                foreign_keys.append(
                    {
                        "column_name": getattr(foreign_key, "column_name", "") or "",
                        "reference_table": getattr(foreign_key, "reference_table", "") or "",
                        "reference_column": getattr(foreign_key, "reference_column", "") or "",
                        "set_name": getattr(foreign_key, "set_name", "") or "",
                    }
                )

            table_key_map[table_name] = {
                "primary_keys": primary_keys,
                "foreign_keys": foreign_keys,
            }

        return table_key_map

    def build_db2_table_lookup(
        self,
        db2_model: DB2Model,
    ) -> dict[str, DB2Table]:
        lookup: dict[str, DB2Table] = {}

        for table in getattr(db2_model, "tables", []) or []:
            table_name = self.to_db2_name(
                getattr(table, "name", "") or "",
            )

            if not table_name:
                continue

            for key in self.name_lookup_keys(table_name):
                lookup[key] = table

        return lookup

    def build_canonical_record_lookup(
        self,
        canonical_schema: CanonicalSchema,
    ) -> dict[str, Any]:
        lookup: dict[str, Any] = {}

        for record in getattr(canonical_schema, "records", []) or []:
            record_name = self.to_db2_name(
                getattr(record, "name", "") or "",
            )

            if not record_name:
                continue

            for key in self.name_lookup_keys(record_name):
                lookup[key] = record

        return lookup

    def build_record_table_map(
        self,
        metadata: SchemaMetadata,
        db2_table_lookup: dict[str, DB2Table],
    ) -> dict[str, str]:
        record_table_map: dict[str, str] = {}

        for record in getattr(metadata, "records", []) or []:
            record_name = self.to_db2_name(
                getattr(record, "name", "") or "",
            )

            if not record_name:
                continue

            table = self.find_table_for_record(
                record_name=record_name,
                db2_table_lookup=db2_table_lookup,
            )

            record_table_map[record_name] = (
                getattr(table, "name", "") if table is not None else record_name
            )

        return record_table_map

    def build_field_map(
        self,
        metadata: SchemaMetadata,
        db2_table_lookup: dict[str, DB2Table],
        record_table_map: dict[str, str],
    ) -> dict[str, dict[str, Any]]:
        field_map: dict[str, dict[str, Any]] = {}

        for record in getattr(metadata, "records", []) or []:
            idms_record_name = self.to_db2_name(
                getattr(record, "name", "") or "",
            )

            if not idms_record_name:
                continue

            table_name = record_table_map.get(
                idms_record_name,
                idms_record_name,
            )

            table = self.find_table_for_record(
                record_name=table_name,
                db2_table_lookup=db2_table_lookup,
            )

            if table is None:
                continue

            column_lookup = self.build_column_lookup(
                table=table,
            )

            source_fields = (
                getattr(record, "mapping_fields", None)
                or getattr(record, "fields", None)
                or []
            )

            for field in source_fields:
                raw_legacy_field_name = str(
                    getattr(field, "name", "") or ""
                ).strip()

                legacy_field_name = self.to_db2_name(
                    raw_legacy_field_name,
                )

                if not legacy_field_name:
                    continue

                column = self.find_column_for_legacy_field(
                    legacy_field_name=legacy_field_name,
                    column_lookup=column_lookup,
                )

                if column is None:
                    continue

                column_name = getattr(column, "name", "") or ""

                host = self.host_variable_name(
                    record=idms_record_name,
                    column=column_name,
                )

                payload = {
                    "record": idms_record_name,
                    "table": getattr(table, "name", "") or "",
                    "column": column_name,
                    "host": host,
                    "legacy_field": legacy_field_name,
                }

                for key in self.name_lookup_keys(legacy_field_name):
                    field_map[key] = payload

                for key in self.name_lookup_keys(raw_legacy_field_name):
                    field_map[key] = payload

                for key in self.name_lookup_keys(column_name):
                    field_map.setdefault(
                        key,
                        payload,
                    )

        return field_map

    def build_column_lookup(
        self,
        table: DB2Table,
    ) -> dict[str, DB2Column]:
        lookup: dict[str, DB2Column] = {}

        for column in getattr(table, "columns", []) or []:
            column_name = self.to_db2_name(
                getattr(column, "name", "") or "",
            )

            if not column_name:
                continue

            for key in self.name_lookup_keys(column_name):
                lookup[key] = column

        return lookup

    def build_calc_key_map(
        self,
        canonical_schema: CanonicalSchema,
        metadata: SchemaMetadata,
        record_table_map: dict[str, str],
        db2_table_lookup: dict[str, DB2Table],
    ) -> dict[str, dict[str, Any]]:
        calc_key_map: dict[str, dict[str, Any]] = {}

        for record in getattr(metadata, "records", []) or []:
            record_name = self.to_db2_name(
                getattr(record, "name", "") or "",
            )

            if not record_name:
                continue

            primary_keys = self.extract_primary_keys_from_record(record)

            if not primary_keys:
                continue

            table_name = record_table_map.get(
                record_name,
                record_name,
            )

            table = self.find_table_for_record(
                record_name=table_name,
                db2_table_lookup=db2_table_lookup,
            )

            physical_primary_keys = []

            if table is not None:
                column_lookup = self.build_column_lookup(table)

                for primary_key in primary_keys:
                    column = self.find_column_for_legacy_field(
                        legacy_field_name=primary_key,
                        column_lookup=column_lookup,
                    )

                    if column is not None:
                        physical_primary_keys.append(
                            getattr(column, "name", "") or primary_key,
                        )
                    else:
                        physical_primary_keys.append(primary_key)
            else:
                physical_primary_keys = primary_keys

            cleaned_primary_keys = self.unique_values(
                [
                    self.to_db2_name(primary_key)
                    for primary_key in physical_primary_keys
                    if primary_key
                ]
            )

            if not cleaned_primary_keys:
                continue

            primary_key = cleaned_primary_keys[0]

            calc_key_map[record_name] = {
                "record": record_name,
                "table": getattr(table, "name", table_name) if table else table_name,
                "key": primary_key,
                "primary_key": primary_key,
                "primary_keys": cleaned_primary_keys,
                "column": primary_key,
                "host": self.host_variable_name(
                    record=record_name,
                    column=primary_key,
                ),
            }

        for record in getattr(canonical_schema, "records", []) or []:
            record_name = self.to_db2_name(
                getattr(record, "name", "") or "",
            )

            if not record_name or record_name in calc_key_map:
                continue

            primary_keys = self.extract_primary_keys_from_record(record)

            if not primary_keys:
                continue

            primary_key = primary_keys[0]

            calc_key_map[record_name] = {
                "record": record_name,
                "table": record_name,
                "key": primary_key,
                "primary_key": primary_key,
                "primary_keys": primary_keys,
                "column": primary_key,
                "host": self.host_variable_name(
                    record=record_name,
                    column=primary_key,
                ),
            }

        return calc_key_map

    def build_relationships_payload(
        self,
        canonical_schema: CanonicalSchema,
        db2_table_lookup: dict[str, DB2Table],
    ) -> list[dict[str, Any]]:
        relationships_payload: list[dict[str, Any]] = []

        for relationship in getattr(canonical_schema, "relationships", []) or []:
            parent_record = self.to_db2_name(
                getattr(relationship, "parent_record", None)
                or getattr(relationship, "owner_record", None)
                or "",
            )

            child_record = self.to_db2_name(
                getattr(relationship, "child_record", None)
                or getattr(relationship, "member_record", None)
                or "",
            )

            set_name = self.to_db2_name(
                getattr(relationship, "set_name", None)
                or getattr(relationship, "name", None)
                or "",
            )

            parent_table = self.find_table_for_record(
                record_name=parent_record,
                db2_table_lookup=db2_table_lookup,
            )

            child_table = self.find_table_for_record(
                record_name=child_record,
                db2_table_lookup=db2_table_lookup,
            )

            parent_keys = []

            if parent_table is not None:
                parent_keys = list(getattr(parent_table, "primary_keys", []) or [])

                if not parent_keys and getattr(parent_table, "primary_key", None):
                    parent_keys = [parent_table.primary_key]

            child_fks = []
            order_by = []

            if child_table is not None and parent_table is not None:
                for foreign_key in getattr(child_table, "foreign_keys", []) or []:
                    fk_set_name = self.to_db2_name(
                        getattr(foreign_key, "set_name", "") or "",
                    )

                    reference_table = self.to_db2_name(
                        getattr(foreign_key, "reference_table", "") or "",
                    )

                    parent_table_name = self.to_db2_name(
                        getattr(parent_table, "name", "") or "",
                    )

                    if set_name and fk_set_name and fk_set_name != set_name:
                        continue

                    if reference_table and reference_table != parent_table_name:
                        continue

                    child_fk = getattr(foreign_key, "column_name", "") or ""

                    if child_fk:
                        child_fks.append(child_fk)
                        order_by.append(child_fk)

            relationships_payload.append(
                {
                    "set_name": set_name,
                    "parent_record": parent_record,
                    "child_record": child_record,
                    "owner_record": parent_record,
                    "member_record": child_record,
                    "parent_table": getattr(parent_table, "name", "") if parent_table else "",
                    "child_table": getattr(child_table, "name", "") if child_table else "",
                    "parent_key": parent_keys[0] if parent_keys else None,
                    "parent_keys": parent_keys,
                    "child_fk": child_fks[0] if child_fks else None,
                    "child_fks": child_fks,
                    "cardinality": getattr(relationship, "cardinality", "1:N") or "1:N",
                    "order_by": order_by,
                }
            )

        return relationships_payload

    def build_set_ordering_map(
        self,
        relationships: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        set_ordering_map: dict[str, dict[str, Any]] = {}

        for relationship in relationships:
            set_name = relationship.get("set_name") or ""

            if not set_name:
                continue

            set_ordering_map[set_name] = {
                "parent_record": relationship.get("parent_record") or "",
                "child_record": relationship.get("child_record") or "",
                "parent_key": relationship.get("parent_key"),
                "parent_keys": relationship.get("parent_keys") or [],
                "child_fk": relationship.get("child_fk"),
                "child_fks": relationship.get("child_fks") or [],
                "order_by": relationship.get("order_by") or [],
            }

        return set_ordering_map

    def build_nullable_fk_map(
        self,
        db2_model: DB2Model,
    ) -> dict[str, Any]:
        nullable_fk_map: dict[str, Any] = {}

        for table in getattr(db2_model, "tables", []) or []:
            table_name = getattr(table, "name", "") or ""

            column_lookup = {
                getattr(column, "name", ""): column
                for column in getattr(table, "columns", []) or []
            }

            for foreign_key in getattr(table, "foreign_keys", []) or []:
                fk_column_name = getattr(foreign_key, "column_name", "") or ""
                fk_column = column_lookup.get(fk_column_name)

                nullable = (
                    getattr(fk_column, "nullable", True)
                    if fk_column is not None
                    else True
                )

                payload = {
                    "nullable": nullable,
                    "set_name": getattr(foreign_key, "set_name", "") or "",
                    "reference_table": getattr(foreign_key, "reference_table", "") or "",
                    "reference_column": getattr(foreign_key, "reference_column", "") or "",
                    "table": table_name,
                    "column": fk_column_name,
                    "null_indicator": self.null_indicator_name(
                        record=table_name,
                        column=fk_column_name,
                    ),
                }

                key = f"{table_name}.{fk_column_name}"
                nullable_fk_map[key] = payload

                set_name = self.to_db2_name(
                    getattr(foreign_key, "set_name", "") or "",
                )

                if set_name:
                    nullable_fk_map[set_name] = payload

        return nullable_fk_map

    def build_date_part_map(
        self,
        metadata: SchemaMetadata,
        db2_table_lookup: dict[str, DB2Table],
        record_table_map: dict[str, str],
    ) -> dict[str, dict[str, Any]]:
        date_part_map: dict[str, dict[str, Any]] = {}

        for record in getattr(metadata, "records", []) or []:
            idms_record_name = self.to_db2_name(
                getattr(record, "name", "") or "",
            )

            if not idms_record_name:
                continue

            table_name = record_table_map.get(
                idms_record_name,
                idms_record_name,
            )

            table = self.find_table_for_record(
                record_name=table_name,
                db2_table_lookup=db2_table_lookup,
            )

            if table is None:
                continue

            date_columns = {
                key: column
                for key, column in self.build_column_lookup(table).items()
                if str(getattr(column, "datatype", "") or "").upper() == "DATE"
            }

            if not date_columns:
                continue

            source_fields = (
                getattr(record, "mapping_fields", None)
                or getattr(record, "fields", None)
                or []
            )

            for field in source_fields:
                raw_legacy_field_name = str(
                    getattr(field, "name", "") or ""
                ).strip()

                legacy_field_name = self.to_db2_name(
                    raw_legacy_field_name,
                )

                if not legacy_field_name:
                    continue

                parsed_candidates = self.parse_date_part_candidates(
                    field_name=legacy_field_name,
                )

                if not parsed_candidates:
                    continue

                for parsed in parsed_candidates:
                    part = parsed["part"]
                    candidate_keys = parsed["candidate_keys"]

                    date_column = self.find_first_existing_column(
                        candidates=candidate_keys,
                        columns=date_columns,
                    )

                    if date_column is None:
                        continue

                    date_column_name = getattr(date_column, "name", "") or ""
                    host = self.host_variable_name(
                        record=idms_record_name,
                        column=date_column_name,
                    )

                    payload = {
                        "record": idms_record_name,
                        "table": getattr(table, "name", "") or "",
                        "column": date_column_name,
                        "host": host,
                        "substring_start": self.DATE_PARTS[part]["substring_start"],
                        "substring_length": self.DATE_PARTS[part]["substring_length"],
                        "part": part,
                        "date_part": part,
                        "legacy_field": legacy_field_name,
                    }

                    for key in self.name_lookup_keys(legacy_field_name):
                        date_part_map[key] = payload

                    for key in self.name_lookup_keys(raw_legacy_field_name):
                        date_part_map[key] = payload

                    break

        return date_part_map

    def parse_date_part(
        self,
        field_name: str,
    ) -> dict[str, Any] | None:
        candidates = self.parse_date_part_candidates(
            field_name=field_name,
        )

        if not candidates:
            return None

        return candidates[0]

    def parse_date_part_candidates(
        self,
        field_name: str,
    ) -> list[dict[str, Any]]:
        normalized = self.to_db2_name(field_name or "")

        if not normalized:
            return []

        tokens = [
            token
            for token in re.split(r"[\s_]+", normalized)
            if token
        ]

        candidates = []

        for index, token in enumerate(tokens):
            part = self.date_part_type(
                token=token,
                tokens=tokens,
            )

            if part is None:
                continue

            base_tokens = tokens[:index] + tokens[index + 1 :]
            date_tokens = tokens.copy()
            date_tokens[index] = "DATE"

            base_name = "_".join(base_tokens)
            date_name = "_".join(date_tokens)
            compact_base = self.compact_name(base_name)

            candidate_keys = self.unique_values(
                [
                    date_name,
                    base_name,
                    compact_base + "_DATE",
                    "DA_" + compact_base + "DATE",
                    "DA_" + date_name,
                    self.remove_record_suffix(date_name),
                    self.remove_record_suffix(base_name),
                    self.remove_record_suffix(compact_base + "_DATE"),
                    self.remove_record_suffix("DA_" + compact_base + "DATE"),
                ]
            )

            candidates.append(
                {
                    "date_key": date_name,
                    "part": part,
                    "tokens": date_tokens,
                    "candidate_keys": candidate_keys,
                }
            )

        return candidates

    def date_part_type(
        self,
        token: str,
        tokens: list[str],
    ) -> str | None:
        token = str(token or "").upper()

        has_dy_dm_dd = (
            "DY" in tokens
            and "DM" in tokens
            and "DD" in tokens
        )

        if token in {"YEAR", "YR", "Y", "YY", "YYYY"}:
            return "YEAR"

        if token in {"MONTH", "MON", "MO", "M", "MM", "DM"}:
            return "MONTH"

        if token in {"DAY", "D", "DD"}:
            return "DAY"

        if token == "DY":
            if has_dy_dm_dd:
                return "YEAR"

            return "DAY"

        return None

    def build_navigation_intent(
        self,
        relationships: list[dict[str, Any]],
    ) -> dict[str, Any]:
        navigation_intent: dict[str, Any] = {}

        for relationship in relationships:
            set_name = relationship.get("set_name") or ""

            if not set_name:
                continue

            navigation_intent[set_name] = {
                "access_pattern": "SET_NAVIGATION",
                "parent_record": relationship.get("parent_record"),
                "child_record": relationship.get("child_record"),
                "parent_key": relationship.get("parent_key"),
                "parent_keys": relationship.get("parent_keys") or [],
                "child_fk": relationship.get("child_fk"),
                "child_fks": relationship.get("child_fks") or [],
                "order_by": relationship.get("order_by") or [],
            }

        return navigation_intent

    def build_output_semantics(
        self,
    ) -> dict[str, Any]:
        return {
            "generated_by": "idms-db2-modernizer-phase1",
            "usage": "IDMS retrieval COBOL to DB2 embedded SQL conversion",
            "physical_types_source": "DB2_DDL",
            "logical_mapping_source": "PHASE1_CANONICAL_METADATA",
            "db2_key_values": ["PK", "FK", "PK/FK"],
            "generated_primary_key_rule": "ID_RECORD_<record_name>",
            "generated_primary_key_datatype": "CHAR(20)",
            "foreign_key_rule": "Use SET relationship and owner primary key columns only.",
            "character_rule": "CHAR by default; VARCHAR only when length equals 100.",
            "numeric_rule": "Numeric COBOL PIC maps to DECIMAL.",
            "date_rule": "Date part recognition remains generic for YEAR, YR, Y, YY, YYYY, DY, MONTH, MON, MO, M, MM, DM, DAY, D, DD.",
        }

    def build_validation_messages(
        self,
        canonical_schema: CanonicalSchema,
        db2_model: DB2Model,
        metadata: SchemaMetadata,
        field_map: dict[str, dict[str, Any]],
    ) -> list[str]:
        messages: list[str] = []

        if not getattr(canonical_schema, "records", []) or []:
            messages.append("No canonical records found.")

        if not getattr(db2_model, "tables", []) or []:
            messages.append("No DB2 tables found.")

        if not getattr(metadata, "records", []) or []:
            messages.append("No IDMS metadata records found.")

        if not field_map:
            messages.append("No field map entries generated.")

        for table in getattr(db2_model, "tables", []) or []:
            primary_keys = list(getattr(table, "primary_keys", []) or [])

            if not primary_keys and getattr(table, "primary_key", None):
                primary_keys = [table.primary_key]

            if not primary_keys:
                messages.append(f"Table {table.name} has no primary key.")
                continue

            column_names = {
                self.to_db2_name(getattr(column, "name", "") or "")
                for column in getattr(table, "columns", []) or []
            }

            for primary_key in primary_keys:
                if self.to_db2_name(primary_key) not in column_names:
                    messages.append(
                        f"Table {table.name} primary key {primary_key} is not present as a DB2 column."
                    )

        return messages

    def parse_db2_datatype(
        self,
        datatype: str,
    ) -> tuple[str, int | None, int | None]:
        value = (datatype or "").strip().upper()

        decimal_match = re.match(
            r"^(DECIMAL|NUMERIC)$(\d+)(?:,\s*(\d+))?$$",
            value,
        )

        if decimal_match:
            return (
                "DECIMAL",
                int(decimal_match.group(2)),
                int(decimal_match.group(3) or 0),
            )

        char_match = re.match(
            r"^(VARCHAR|CHAR|CHARACTER)$(\d+)$$",
            value,
        )

        if char_match:
            datatype_name = char_match.group(1)

            if datatype_name == "CHARACTER":
                datatype_name = "CHAR"

            return (
                datatype_name,
                int(char_match.group(2)),
                None,
            )

        if value in {"INTEGER", "INT"}:
            return "INTEGER", 9, 0

        if value == "BIGINT":
            return "BIGINT", 18, 0

        if value == "SMALLINT":
            return "INTEGER", 9, 0

        if value == "DATE":
            return "DATE", None, None

        if value == "TIMESTAMP":
            return "TIMESTAMP", None, None

        return value or "CHAR", None, None

    def host_variable_name(
        self,
        record: str,
        column: str,
    ) -> str:
        record_name = self.to_cobol_name(record or "")
        column_name = self.to_cobol_name(column or "")

        return f"HV-{record_name}-{column_name}"

    def null_indicator_name(
        self,
        record: str,
        column: str,
    ) -> str:
        record_name = self.to_cobol_name(record or "")
        column_name = self.to_cobol_name(column or "")

        return f"NI-{record_name}-{column_name}"

    def find_table_for_record(
        self,
        record_name: str,
        db2_table_lookup: dict[str, DB2Table],
    ) -> DB2Table | None:
        for key in self.name_lookup_keys(record_name):
            if key in db2_table_lookup:
                return db2_table_lookup[key]

        return None

    def find_column_for_legacy_field(
        self,
        legacy_field_name: str,
        column_lookup: dict[str, DB2Column],
    ) -> DB2Column | None:
        for key in self.name_lookup_keys(legacy_field_name):
            if key in column_lookup:
                return column_lookup[key]

        legacy_base = self.remove_record_suffix(legacy_field_name)
        legacy_compact = self.compact_name(legacy_base)

        for column_key, column in column_lookup.items():
            column_base = self.remove_record_suffix(column_key)
            column_generated_removed = self.remove_generated_suffix(column_key)
            column_compact = self.compact_name(column_generated_removed or column_base)

            if legacy_base == column_base:
                return column

            if legacy_base == column_generated_removed:
                return column

            if legacy_compact and legacy_compact == column_compact:
                return column

            if legacy_compact and column_compact.endswith(legacy_compact):
                return column

            if legacy_compact and legacy_compact in column_compact:
                return column

        return None

    def find_first_existing_column(
        self,
        candidates: list[str],
        columns: dict[str, DB2Column],
    ) -> DB2Column | None:
        for candidate in candidates:
            for key in self.name_lookup_keys(candidate):
                if key in columns:
                    return columns[key]

            candidate_base = self.remove_record_suffix(candidate)
            candidate_generated_removed = self.remove_generated_suffix(candidate)
            candidate_compact = self.compact_name(candidate_generated_removed or candidate_base)

            for column_key, column in columns.items():
                column_base = self.remove_record_suffix(column_key)
                column_generated_removed = self.remove_generated_suffix(column_key)
                column_compact = self.compact_name(column_generated_removed or column_base)

                if candidate_base == column_base:
                    return column

                if candidate_generated_removed == column_generated_removed:
                    return column

                if candidate_compact and candidate_compact == column_compact:
                    return column

                if candidate_compact and candidate_compact in column_compact:
                    return column

                if candidate_compact and column_compact.endswith(candidate_compact):
                    return column

        return None

    def extract_primary_keys_from_record(
        self,
        record,
    ) -> list[str]:
        primary_keys = []

        explicit_primary_keys = getattr(record, "primary_keys", None)

        if explicit_primary_keys:
            if isinstance(explicit_primary_keys, list):
                primary_keys.extend(explicit_primary_keys)
            else:
                primary_keys.append(explicit_primary_keys)

        primary_key = getattr(record, "primary_key", None)

        if primary_key:
            primary_keys.append(primary_key)

        return self.unique_values(
            [
                self.to_db2_name(primary_key)
                for primary_key in primary_keys
                if primary_key
            ]
        )

    def name_lookup_keys(
        self,
        value: str | None,
    ) -> list[str]:
        original = str(value or "").strip().upper()

        if not original:
            return []

        db2_name = self.to_db2_name(original)
        cobol_name = self.to_cobol_name(original)
        no_record_suffix = self.remove_record_suffix(db2_name)
        no_generated_suffix = self.remove_generated_suffix(db2_name)
        compact = self.compact_name(no_generated_suffix or no_record_suffix or db2_name)

        return self.unique_values(
            [
                original,
                db2_name,
                cobol_name,
                no_record_suffix,
                no_generated_suffix,
                compact,
            ]
        )

    def to_db2_name(
        self,
        value: str | None,
    ) -> str:
        text = str(value or "").strip().upper()

        if not text:
            return ""

        text = text.replace("\u00a0", " ")
        text = text.replace("\t", " ")
        text = re.sub(r"[^A-Z0-9]+", "_", text)
        text = re.sub(r"_+", "_", text)
        text = text.strip("_")

        return text

    def to_cobol_name(
        self,
        value: str | None,
    ) -> str:
        text = self.to_db2_name(value)

        text = text.replace("_", "-")
        text = re.sub(r"-+", "-", text)

        return text.strip("-")

    def remove_record_suffix(
        self,
        value: str | None,
    ) -> str:
        text = self.to_db2_name(value)

        if not text:
            return ""

        text = re.sub(r"[_\-\s]+[0-9]{4}$", "", text)
        text = re.sub(r"[0-9]{4}$", "", text)
        text = re.sub(r"[_\-\s]+$", "", text)

        return text

    def remove_generated_suffix(
        self,
        value: str | None,
    ) -> str:
        text = self.to_db2_name(value)

        if not text:
            return ""

        text = re.sub(r"_479[A-Z0-9]+$", "", text)
        text = re.sub(r"479[A-Z0-9]+$", "", text)
        text = re.sub(r"[_\-\s]+$", "", text)

        return text

    def compact_name(
        self,
        value: str | None,
    ) -> str:
        return re.sub(
            r"[^A-Z0-9]",
            "",
            str(value or "").upper(),
        )

    def unique_values(
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