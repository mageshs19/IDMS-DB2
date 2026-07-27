import json
import re

from datetime import datetime
from typing import Any

from idms_modernizer.domain.canonical_models import CanonicalSchema
from idms_modernizer.domain.db2_models import DB2Model, DB2Table, DB2Column
from idms_modernizer.domain.schema_models import SchemaMetadata
from idms_modernizer.services.name_normalizer import NameNormalizer


class Phase2MetadataGenerator:
    """
    Generates Phase 2 metadata JSON from Phase 1 outputs.

    Supports:
    - Record/table mapping.
    - Field/column host variable mapping.
    - Date part mapping for:
      YEAR / MONTH / DAY
      YR / MO / DY
      Y / M / D
      YY / MM / DD
      YYYY / MM / DD
      DY / DM / DD
    - CALC key mapping.
    - FK/nullability hints.
    - Set relationship payload.
    """

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
        payload = self.generate(
            canonical_schema=canonical_schema,
            db2_model=db2_model,
            metadata=metadata,
        )

        return json.dumps(
            payload,
            indent=2,
        )

    def generate(
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

        record_table_map = self.build_record_table_map(
            canonical_schema=canonical_schema,
            metadata=metadata,
        )

        records_payload = self.build_records_payload(
            db2_model=db2_model,
        )

        field_map = self.build_field_map(
            metadata=metadata,
            canonical_schema=canonical_schema,
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
            "date_part_map": date_part_map,
            "navigation_intent": navigation_intent,
            "output_semantics": output_semantics,
            "validation_messages": validation_messages,
            "canonical_record_lookup_count": len(canonical_record_lookup),
        }

    def build_db2_table_lookup(
        self,
        db2_model: DB2Model,
    ) -> dict[str, DB2Table]:
        lookup: dict[str, DB2Table] = {}

        for table in getattr(db2_model, "tables", []) or []:
            table_name = NameNormalizer.normalize(
                getattr(table, "name", ""),
            )

            if table_name:
                lookup[table_name] = table

            suffix_removed = self.remove_record_suffix(
                table_name,
            )

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
                getattr(record, "name", ""),
            )

            if record_name:
                lookup[record_name] = record

        return lookup

    def build_record_table_map(
        self,
        canonical_schema: CanonicalSchema,
        metadata: SchemaMetadata,
    ) -> dict[str, str]:
        record_table_map: dict[str, str] = {}

        for record in getattr(canonical_schema, "records", []) or []:
            canonical_name = NameNormalizer.normalize(
                getattr(record, "name", ""),
            )

            if canonical_name:
                record_table_map[canonical_name] = canonical_name

        for record in getattr(metadata, "records", []) or []:
            metadata_name = NameNormalizer.normalize(
                getattr(record, "name", ""),
            )

            if metadata_name and metadata_name not in record_table_map:
                record_table_map[metadata_name] = metadata_name

        return record_table_map

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
                    }
                )

            records_payload.append(
                {
                    "name": getattr(table, "name", ""),
                    "table": getattr(table, "name", ""),
                    "primary_key": getattr(table, "primary_key", None),
                    "fields": fields_payload,
                }
            )

        return records_payload

    def build_field_map(
        self,
        metadata: SchemaMetadata,
        canonical_schema: CanonicalSchema,
        db2_table_lookup: dict[str, DB2Table],
        record_table_map: dict[str, str],
    ) -> dict[str, dict[str, Any]]:
        field_map: dict[str, dict[str, Any]] = {}

        for record in getattr(metadata, "records", []) or []:
            idms_record_name = NameNormalizer.normalize(
                getattr(record, "name", ""),
            )

            if not idms_record_name:
                continue

            table_name = record_table_map.get(
                idms_record_name,
                idms_record_name,
            )

            table = db2_table_lookup.get(
                table_name,
            )

            if table is None:
                continue

            db2_columns = {
                NameNormalizer.normalize(getattr(column, "name", "")): column
                for column in getattr(table, "columns", []) or []
            }

            source_fields = (
                getattr(record, "mapping_fields", None)
                or getattr(record, "fields", [])
                or []
            )

            for field in source_fields:
                legacy_field_name = NameNormalizer.normalize(
                    getattr(field, "name", ""),
                )

                if not legacy_field_name:
                    continue

                physical_column_name = self.find_matching_column(
                    legacy_field_name=legacy_field_name,
                    db2_columns=db2_columns,
                )

                if not physical_column_name:
                    continue

                host = self.host_variable(
                    record_name=idms_record_name,
                    column_name=physical_column_name,
                    remove_suffix=True,
                )

                field_map[legacy_field_name] = {
                    "host": host,
                    "record": idms_record_name,
                    "table": table.name,
                    "column": physical_column_name,
                    "legacy_field": legacy_field_name,
                }

                suffix_removed_legacy = self.remove_record_suffix(
                    legacy_field_name,
                )

                if suffix_removed_legacy and suffix_removed_legacy not in field_map:
                    field_map[suffix_removed_legacy] = {
                        "host": host,
                        "record": idms_record_name,
                        "table": table.name,
                        "column": physical_column_name,
                        "legacy_field": legacy_field_name,
                    }

        return field_map

    def build_calc_key_map(
        self,
        canonical_schema: CanonicalSchema,
        metadata: SchemaMetadata,
        record_table_map: dict[str, str],
    ) -> dict[str, dict[str, Any]]:
        calc_key_map: dict[str, dict[str, Any]] = {}

        for record in getattr(metadata, "records", []) or []:
            primary_key = getattr(record, "primary_key", None)

            if not primary_key:
                continue

            idms_record_name = NameNormalizer.normalize(
                getattr(record, "name", ""),
            )

            table_name = record_table_map.get(
                idms_record_name,
                idms_record_name,
            )

            normalized_primary_key = NameNormalizer.normalize(
                primary_key,
            )

            calc_key_map[idms_record_name] = {
                "record": idms_record_name,
                "table": table_name,
                "key": normalized_primary_key,
                "primary_key": normalized_primary_key,
                "column": normalized_primary_key,
                "host": self.host_variable(
                    record_name=idms_record_name,
                    column_name=normalized_primary_key,
                    remove_suffix=True,
                ),
            }

        for record in getattr(canonical_schema, "records", []) or []:
            primary_key = getattr(record, "primary_key", None)

            if not primary_key:
                continue

            record_name = NameNormalizer.normalize(
                getattr(record, "name", ""),
            )

            normalized_primary_key = NameNormalizer.normalize(
                primary_key,
            )

            if record_name not in calc_key_map:
                calc_key_map[record_name] = {
                    "record": record_name,
                    "table": record_name,
                    "key": normalized_primary_key,
                    "primary_key": normalized_primary_key,
                    "column": normalized_primary_key,
                    "host": self.host_variable(
                        record_name=record_name,
                        column_name=normalized_primary_key,
                        remove_suffix=True,
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
            parent_record = NameNormalizer.normalize(
                getattr(relationship, "parent_record", ""),
            )

            child_record = NameNormalizer.normalize(
                getattr(relationship, "child_record", ""),
            )

            set_name = NameNormalizer.normalize(
                getattr(relationship, "set_name", ""),
            )

            parent_table = db2_table_lookup.get(
                parent_record,
            )

            child_table = db2_table_lookup.get(
                child_record,
            )

            parent_key = (
                getattr(parent_table, "primary_key", None)
                if parent_table is not None
                else None
            )

            child_fk = None
            order_by: list[str] = []

            if child_table is not None:
                for foreign_key in getattr(child_table, "foreign_keys", []) or []:
                    if (
                        parent_table is not None
                        and NameNormalizer.normalize(getattr(foreign_key, "reference_table", ""))
                        == NameNormalizer.normalize(getattr(parent_table, "name", ""))
                    ):
                        child_fk = getattr(foreign_key, "column_name", None)
                        order_by = [child_fk] if child_fk else []
                        break

            relationships_payload.append(
                {
                    "set_name": set_name,
                    "parent_record": parent_record,
                    "child_record": child_record,
                    "parent_key": parent_key,
                    "child_fk": child_fk,
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
            set_name = relationship.get(
                "set_name",
            )

            if not set_name:
                continue

            set_ordering_map[set_name] = {
                "order_by": relationship.get("order_by") or [],
            }

        return set_ordering_map

    def build_nullable_fk_map(
        self,
        db2_model: DB2Model,
    ) -> dict[str, bool]:
        nullable_fk_map: dict[str, bool] = {}

        for table in getattr(db2_model, "tables", []) or []:
            column_lookup = {
                getattr(column, "name", ""): column
                for column in getattr(table, "columns", []) or []
            }

            for foreign_key in getattr(table, "foreign_keys", []) or []:
                fk_column_name = getattr(foreign_key, "column_name", "")
                fk_column = column_lookup.get(fk_column_name)

                nullable_fk_map[f"{table.name}.{fk_column_name}"] = (
                    getattr(fk_column, "nullable", True)
                    if fk_column is not None
                    else True
                )

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
                getattr(record, "name", ""),
            )

            if not idms_record_name:
                continue

            table_name = record_table_map.get(
                idms_record_name,
                idms_record_name,
            )

            table = db2_table_lookup.get(
                table_name,
            )

            if table is None:
                continue

            date_columns = {
                NameNormalizer.normalize(getattr(column, "name", "")): column
                for column in getattr(table, "columns", []) or []
                if str(getattr(column, "datatype", "")).upper() == "DATE"
            }

            source_fields = (
                getattr(record, "mapping_fields", None)
                or getattr(record, "fields", [])
                or []
            )

            for field in source_fields:
                legacy_field_name = NameNormalizer.normalize(
                    getattr(field, "name", ""),
                )

                parsed = self.parse_date_part(
                    field_name=legacy_field_name,
                )

                if parsed is None:
                    continue

                part = parsed["part"]
                candidate_columns = parsed["candidate_columns"]

                physical_date_column = self.find_first_existing_column(
                    candidates=candidate_columns,
                    columns=date_columns,
                )

                if physical_date_column is None:
                    continue

                date_part_meta = self.DATE_PARTS[part]

                date_part_map[legacy_field_name] = {
                    "host": self.host_variable(
                        record_name=idms_record_name,
                        column_name=physical_date_column,
                        remove_suffix=True,
                    ),
                    "record": idms_record_name,
                    "table": table.name,
                    "column": physical_date_column,
                    "date_part": part,
                    "substring_start": date_part_meta["substring_start"],
                    "substring_length": date_part_meta["substring_length"],
                }

        return date_part_map

    def build_navigation_intent(
        self,
        relationships: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        navigation_intent: dict[str, dict[str, Any]] = {}

        for relationship in relationships:
            set_name = relationship.get(
                "set_name",
            )

            if not set_name:
                continue

            navigation_intent[set_name] = {
                "access_pattern": "SET_NAVIGATION",
                "parent_record": relationship.get("parent_record"),
                "child_record": relationship.get("child_record"),
                "parent_key": relationship.get("parent_key"),
                "child_fk": relationship.get("child_fk"),
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
        }

    def build_validation_messages(
        self,
        canonical_schema: CanonicalSchema,
        db2_model: DB2Model,
        metadata: SchemaMetadata,
        field_map: dict[str, dict[str, Any]],
    ) -> list[str]:
        messages: list[str] = []

        if not getattr(canonical_schema, "records", []):
            messages.append("No canonical records found.")

        if not getattr(db2_model, "tables", []):
            messages.append("No DB2 tables found.")

        if not getattr(metadata, "records", []):
            messages.append("No IDMS metadata records found.")

        if not field_map:
            messages.append("No field map entries generated.")

        for table in getattr(db2_model, "tables", []) or []:
            primary_key = getattr(table, "primary_key", None)

            if not primary_key:
                continue

            column_names = {
                NameNormalizer.normalize(getattr(column, "name", ""))
                for column in getattr(table, "columns", []) or []
            }

            if NameNormalizer.normalize(primary_key) not in column_names:
                messages.append(
                    f"Table {table.name} primary key {primary_key} is not present as a DB2 column."
                )

        return messages

    def find_matching_column(
        self,
        legacy_field_name: str,
        db2_columns: dict[str, DB2Column],
    ) -> str | None:
        normalized = NameNormalizer.normalize(
            legacy_field_name,
        )

        if normalized in db2_columns:
            return normalized

        suffix_removed = self.remove_record_suffix(
            normalized,
        )

        for column_name in db2_columns:
            if self.remove_record_suffix(column_name) == suffix_removed:
                return column_name

        return None

    def parse_date_part(
        self,
        field_name: str,
    ) -> dict[str, Any] | None:
        tokens = self.split_tokens(
            value=field_name,
        )

        if len(tokens) < 2:
            return None

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

            base_name = " ".join(base_tokens)
            date_name = " ".join(date_tokens)

            return {
                "part": part,
                "candidate_columns": self.unique_values(
                    [
                        date_name,
                        base_name,
                    ]
                ),
            }

        return None

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

    def find_first_existing_column(
        self,
        candidates: list[str],
        columns: dict[str, DB2Column],
    ) -> str | None:
        for candidate in candidates:
            normalized_candidate = NameNormalizer.normalize(
                candidate,
            )

            if normalized_candidate in columns:
                return normalized_candidate

            suffix_removed_candidate = self.remove_record_suffix(
                normalized_candidate,
            )

            for column_name in columns:
                if self.remove_record_suffix(column_name) == suffix_removed_candidate:
                    return column_name

        return None

    def host_variable(
        self,
        record_name: str,
        column_name: str,
        remove_suffix: bool = True,
    ) -> str:
        record = NameNormalizer.normalize(
            record_name,
        ).replace(
            " ",
            "-",
        )

        column = NameNormalizer.normalize(
            column_name,
        )

        if remove_suffix:
            column = self.remove_record_suffix(
                column,
            )

        column = column.replace(
            " ",
            "-",
        )

        return f"HV-{record}-{column}"

    def parse_db2_datatype(
        self,
        datatype: str,
    ) -> tuple[str, int | None, int | None]:
        value = (
            datatype
            or "VARCHAR(255)"
        ).strip().upper()

        decimal_match = re.match(
            r"^(DECIMAL|NUMERIC)$(\d+),\s*(\d+)$$",
            value,
        )

        if decimal_match:
            return (
                "DECIMAL",
                int(decimal_match.group(2)),
                int(decimal_match.group(3)),
            )

        varchar_match = re.match(
            r"^(VARCHAR|CHAR)$(\d+)$$",
            value,
        )

        if varchar_match:
            return (
                varchar_match.group(1),
                int(varchar_match.group(2)),
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

        return value, None, None

    def remove_record_suffix(
        self,
        field_name: str,
    ) -> str:
        normalized = NameNormalizer.normalize(
            field_name,
        )

        parts = normalized.split()

        if (
            len(parts) > 1
            and parts[-1].isdigit()
            and len(parts[-1]) == 4
        ):
            return " ".join(
                parts[:-1],
            )

        return normalized

    def split_tokens(
        self,
        value: str,
    ) -> list[str]:
        normalized = NameNormalizer.normalize(
            value,
        )

        return [
            token.upper()
            for token in re.split(
                r"[\s_-]+",
                normalized,
            )
            if token
        ]

    def unique_values(
        self,
        values: list[str],
    ) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()

        for value in values:
            normalized = NameNormalizer.normalize(
                value,
            )

            if not normalized:
                continue

            if normalized in seen:
                continue

            seen.add(
                normalized,
            )

            result.append(
                normalized,
            )

        return result