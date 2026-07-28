import json
import re

from datetime import datetime
from typing import Any

from idms_modernizer.domain.canonical_models import CanonicalSchema
from idms_modernizer.domain.db2_models import DB2Model, DB2Table, DB2Column
from idms_modernizer.domain.schema_models import SchemaMetadata
from idms_modernizer.services.name_normalizer import NameNormalizer


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

            for column in getattr(table, "columns", []) or []:
                datatype, length, scale = self.parse_db2_datatype(
                    getattr(column, "datatype", ""),
                )

                fields_payload.append(
                    {
                        "name": getattr(column, "name", ""),
                        "column": getattr(column, "name", ""),
                        "datatype": datatype,
                        "length": length,
                        "scale": scale,
                        "nullable": getattr(column, "nullable", True),
                        "primary_key": getattr(column, "primary_key", False),
                        "generated": getattr(column, "generated", False),
                        "source_kind": getattr(column, "source_kind", ""),
                    }
                )

            primary_keys = list(getattr(table, "primary_keys", []) or [])

            if not primary_keys and getattr(table, "primary_key", None):
                primary_keys = [table.primary_key]

            records_payload.append(
                {
                    "name": getattr(table, "name", ""),
                    "table": getattr(table, "name", ""),
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
            table_name = NameNormalizer.normalize(getattr(table, "name", "") or "")

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

            if table_name:
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
            table_name = NameNormalizer.normalize(
                getattr(table, "name", "") or "",
            )

            if table_name:
                lookup[table_name] = table

            suffix_removed = self.remove_record_suffix(table_name)

            if suffix_removed:
                lookup[suffix_removed] = table

        return lookup

    def build_canonical_record_lookup(
        self,
        canonical_schema: CanonicalSchema,
    ) -> dict[str, Any]:
        lookup: dict[str, Any] = {}

        for record in getattr(canonical_schema, "records", []) or []:
            record_name = NameNormalizer.normalize(
                getattr(record, "name", "") or "",
            )

            if record_name:
                lookup[record_name] = record

            suffix_removed = self.remove_record_suffix(record_name)

            if suffix_removed:
                lookup[suffix_removed] = record

        return lookup

    def build_record_table_map(
        self,
        metadata: SchemaMetadata,
        db2_table_lookup: dict[str, DB2Table],
    ) -> dict[str, str]:
        record_table_map: dict[str, str] = {}

        for record in getattr(metadata, "records", []) or []:
            record_name = NameNormalizer.normalize(
                getattr(record, "name", "") or "",
            )

            if not record_name:
                continue

            table = db2_table_lookup.get(record_name)

            if table is None:
                suffix_removed = self.remove_record_suffix(record_name)
                table = db2_table_lookup.get(suffix_removed)

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
            idms_record_name = NameNormalizer.normalize(
                getattr(record, "name", "") or "",
            )

            if not idms_record_name:
                continue

            table_name = record_table_map.get(
                idms_record_name,
                idms_record_name,
            )

            table = db2_table_lookup.get(
                NameNormalizer.normalize(table_name),
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
                legacy_field_name = NameNormalizer.normalize(
                    getattr(field, "name", "") or "",
                )

                if not legacy_field_name:
                    continue

                column = column_lookup.get(legacy_field_name)

                if column is None:
                    suffix_removed = self.remove_record_suffix(legacy_field_name)
                    column = column_lookup.get(suffix_removed)

                if column is None:
                    continue

                field_map[legacy_field_name] = {
                    "record": idms_record_name,
                    "table": getattr(table, "name", ""),
                    "column": getattr(column, "name", ""),
                    "host": self.host_variable_name(
                        record=idms_record_name,
                        column=getattr(column, "name", ""),
                    ),
                }

        return field_map

    def build_column_lookup(
        self,
        table: DB2Table,
    ) -> dict[str, DB2Column]:
        lookup: dict[str, DB2Column] = {}

        for column in getattr(table, "columns", []) or []:
            column_name = NameNormalizer.normalize(
                getattr(column, "name", "") or "",
            )

            if column_name:
                lookup[column_name] = column

            suffix_removed = self.remove_record_suffix(column_name)

            if suffix_removed:
                lookup[suffix_removed] = column

        return lookup

    def build_calc_key_map(
        self,
        canonical_schema: CanonicalSchema,
        metadata: SchemaMetadata,
        record_table_map: dict[str, str],
    ) -> dict[str, dict[str, Any]]:
        calc_key_map: dict[str, dict[str, Any]] = {}

        for record in getattr(metadata, "records", []) or []:
            record_name = NameNormalizer.normalize(
                getattr(record, "name", "") or "",
            )

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

            cleaned_primary_keys = []

            for primary_key_value in primary_keys:
                normalized_primary_key = NameNormalizer.normalize(
                    primary_key_value,
                )

                if not normalized_primary_key:
                    continue

                if normalized_primary_key in cleaned_primary_keys:
                    continue

                cleaned_primary_keys.append(normalized_primary_key)

            if not cleaned_primary_keys:
                continue

            calc_key_map[record_name] = {
                "record": record_name,
                "table": record_table_map.get(record_name, record_name),
                "primary_key": cleaned_primary_keys[0],
                "primary_keys": cleaned_primary_keys,
            }

        return calc_key_map

    def build_relationships_payload(
        self,
        canonical_schema: CanonicalSchema,
        db2_table_lookup: dict[str, DB2Table],
    ) -> list[dict[str, Any]]:
        relationships_payload: list[dict[str, Any]] = []

        for relationship in getattr(canonical_schema, "relationships", []) or []:
            parent_record = NameNormalizer.normalize(
                getattr(relationship, "parent_record", None)
                or getattr(relationship, "owner_record", None)
                or "",
            )

            child_record = NameNormalizer.normalize(
                getattr(relationship, "child_record", None)
                or getattr(relationship, "member_record", None)
                or "",
            )

            set_name = NameNormalizer.normalize(
                getattr(relationship, "set_name", None)
                or getattr(relationship, "name", None)
                or "",
            )

            parent_table = db2_table_lookup.get(parent_record)
            child_table = db2_table_lookup.get(child_record)

            parent_keys = []
            child_fks = []

            if parent_table is not None:
                parent_keys = list(getattr(parent_table, "primary_keys", []) or [])

                if not parent_keys and getattr(parent_table, "primary_key", None):
                    parent_keys = [parent_table.primary_key]

            if child_table is not None:
                for foreign_key in getattr(child_table, "foreign_keys", []) or []:
                    fk_set_name = NameNormalizer.normalize(
                        getattr(foreign_key, "set_name", "") or "",
                    )

                    if set_name and fk_set_name and fk_set_name != set_name:
                        continue

                    child_fks.append(
                        getattr(foreign_key, "column_name", "") or "",
                    )

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
                    "order_by": getattr(relationship, "order_by", []) or [],
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
            column_lookup = {
                getattr(column, "name", ""): column
                for column in getattr(table, "columns", []) or []
            }

            for foreign_key in getattr(table, "foreign_keys", []) or []:
                fk_column_name = getattr(foreign_key, "column_name", "")
                fk_column = column_lookup.get(fk_column_name)

                key = f"{getattr(table, 'name', '')}.{fk_column_name}"

                nullable_fk_map[key] = {
                    "nullable": (
                        getattr(fk_column, "nullable", True)
                        if fk_column is not None
                        else True
                    ),
                    "set_name": getattr(foreign_key, "set_name", "") or "",
                    "reference_table": getattr(foreign_key, "reference_table", "") or "",
                    "reference_column": getattr(foreign_key, "reference_column", "") or "",
                }

        return nullable_fk_map

    def build_date_part_map(
        self,
        metadata: SchemaMetadata,
        db2_table_lookup: dict[str, DB2Table],
        record_table_map: dict[str, str],
    ) -> dict[str, dict[str, Any]]:
        date_part_map: dict[str, dict[str, Any]] = {}

        for record in getattr(metadata, "records", []) or []:
            idms_record_name = NameNormalizer.normalize(
                getattr(record, "name", "") or "",
            )

            if not idms_record_name:
                continue

            table_name = record_table_map.get(
                idms_record_name,
                idms_record_name,
            )

            table = db2_table_lookup.get(
                NameNormalizer.normalize(table_name),
            )

            if table is None:
                continue

            date_columns = {
                NameNormalizer.normalize(getattr(column, "name", "") or ""): column
                for column in getattr(table, "columns", []) or []
                if str(getattr(column, "datatype", "")).upper() == "DATE"
            }

            source_fields = (
                getattr(record, "mapping_fields", None)
                or getattr(record, "fields", None)
                or []
            )

            for field in source_fields:
                legacy_field_name = NameNormalizer.normalize(
                    getattr(field, "name", "") or "",
                )

                parsed = self.parse_date_part(
                    field_name=legacy_field_name,
                )

                if parsed is None:
                    continue

                part = parsed["part"]
                date_key = parsed["date_key"]

                date_column = date_columns.get(date_key)

                if date_column is None:
                    suffix_removed = self.remove_record_suffix(date_key)
                    date_column = date_columns.get(suffix_removed)

                if date_column is None:
                    continue

                date_part_map[legacy_field_name] = {
                    "record": idms_record_name,
                    "table": getattr(table, "name", ""),
                    "column": getattr(date_column, "name", ""),
                    "host": self.host_variable_name(
                        record=idms_record_name,
                        column=getattr(date_column, "name", ""),
                    ),
                    "substring_start": self.DATE_PARTS[part]["substring_start"],
                    "substring_length": self.DATE_PARTS[part]["substring_length"],
                    "part": part,
                }

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
        normalized = NameNormalizer.normalize(field_name or "")

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

            date_tokens = tokens.copy()
            date_tokens[index] = "DATE"

            date_key = "_".join(date_tokens)

            candidates.append(
                {
                    "date_key": date_key,
                    "part": part,
                    "tokens": date_tokens,
                }
            )

        return candidates

    def date_part_type(
        self,
        token: str,
        tokens: list[str],
    ) -> str | None:
        token = token.upper()

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
                NameNormalizer.normalize(getattr(column, "name", "") or "")
                for column in getattr(table, "columns", []) or []
            }

            for primary_key in primary_keys:
                if NameNormalizer.normalize(primary_key) not in column_names:
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
            return (
                "VARCHAR" if char_match.group(1) == "VARCHAR" else "CHAR",
                int(char_match.group(2)),
                None,
            )

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
        record_name = NameNormalizer.normalize(record or "")
        column_name = NameNormalizer.normalize(column or "")
        return f"HV-{record_name}-{column_name}"

    def remove_record_suffix(
        self,
        value: str,
    ) -> str:
        text = NameNormalizer.normalize(value or "")

        if not text:
            return ""

        text = text.replace(" ", "_")

        return re.sub(
            r"_[0-9]{4}$",
            "",
            text,
        )