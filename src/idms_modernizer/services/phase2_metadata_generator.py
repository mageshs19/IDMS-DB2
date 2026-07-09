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

    Inputs:
    - CanonicalSchema
    - DB2Model
    - SchemaMetadata

    Output:
    - Phase 2 metadata JSON compatible with the Phase 2 converter.

    Purpose:
    - Map IDMS record names to DB2 table names.
    - Map IDMS field names to DB2 host variables.
    - Provide set relationship metadata.
    - Provide date-part metadata for YEAR/MONTH/DAY legacy fields.
    - Provide nullable FK hints.
    - Provide CALC key mappings.
    - Provide enough schema information for Phase 2 when DDL is absent.
    """

    VERSION = "1.0"

    DATE_PARTS = {
        "YEAR": {
            "substring_start": 3,
            "substring_length": 2
        },
        "MONTH": {
            "substring_start": 6,
            "substring_length": 2
        },
        "DAY": {
            "substring_start": 9,
            "substring_length": 2
        }
    }

    def generate(
        self,
        canonical_schema: CanonicalSchema,
        db2_model: DB2Model,
        metadata: SchemaMetadata
    ) -> dict[str, Any]:

        db2_table_lookup = self._build_db2_table_lookup(
            db2_model
        )

        canonical_record_lookup = self._build_canonical_record_lookup(
            canonical_schema
        )

        record_table_map = self._build_record_table_map(
            canonical_schema=canonical_schema,
            metadata=metadata
        )

        records_payload = self._build_records_payload(
            db2_model=db2_model
        )

        field_map = self._build_field_map(
            metadata=metadata,
            canonical_schema=canonical_schema,
            db2_table_lookup=db2_table_lookup,
            record_table_map=record_table_map
        )

        calc_key_map = self._build_calc_key_map(
            canonical_schema=canonical_schema,
            metadata=metadata,
            record_table_map=record_table_map
        )

        relationships_payload = self._build_relationships_payload(
            canonical_schema=canonical_schema,
            db2_table_lookup=db2_table_lookup
        )

        set_ordering_map = self._build_set_ordering_map(
            relationships_payload
        )

        nullable_fk_map = self._build_nullable_fk_map(
            db2_model=db2_model
        )

        date_part_map = self._build_date_part_map(
            metadata=metadata,
            canonical_schema=canonical_schema,
            db2_table_lookup=db2_table_lookup,
            record_table_map=record_table_map
        )

        navigation_intent = self._build_navigation_intent(
            relationships_payload
        )

        output_semantics = self._build_output_semantics()

        validation_messages = self._build_validation_messages(
            canonical_schema=canonical_schema,
            db2_model=db2_model,
            metadata=metadata,
            field_map=field_map
        )

        payload = {
            "version": self.VERSION,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "source": "PHASE1",
            "schema_source": "PHASE1_CANONICAL_DB2_METADATA",
            "record_table_map": record_table_map,
            "records": records_payload,
            "relationships": relationships_payload,
            "field_map": field_map,
            "calc_key_map": calc_key_map,
            "set_ordering_map": set_ordering_map,
            "navigation_intent": navigation_intent,
            "nullable_fk_map": nullable_fk_map,
            "date_part_map": date_part_map,
            "output_semantics": output_semantics,
            "paragraph_operation_graph": {},
            "validation_messages": validation_messages
        }

        return payload

    def generate_json(
        self,
        canonical_schema: CanonicalSchema,
        db2_model: DB2Model,
        metadata: SchemaMetadata
    ) -> str:

        payload = self.generate(
            canonical_schema=canonical_schema,
            db2_model=db2_model,
            metadata=metadata
        )

        return json.dumps(
            payload,
            indent=2
        )

    def _build_db2_table_lookup(
        self,
        db2_model: DB2Model
    ) -> dict[str, DB2Table]:

        lookup: dict[str, DB2Table] = {}

        for table in db2_model.tables:
            lookup[
                NameNormalizer.normalize(table.name)
            ] = table

        return lookup

    def _build_canonical_record_lookup(
        self,
        canonical_schema: CanonicalSchema
    ) -> dict[str, Any]:

        lookup: dict[str, Any] = {}

        for record in canonical_schema.records:
            lookup[
                NameNormalizer.normalize(record.name)
            ] = record

        return lookup

    def _build_record_table_map(
        self,
        canonical_schema: CanonicalSchema,
        metadata: SchemaMetadata
    ) -> dict[str, str]:

        record_table_map: dict[str, str] = {}

        for record in canonical_schema.records:
            canonical_name = NameNormalizer.normalize(
                record.name
            )

            record_table_map[
                canonical_name
            ] = canonical_name

        for record in metadata.records:
            idms_record_name = NameNormalizer.normalize(
                record.name
            )

            canonical_record_name = NameNormalizer.normalize(
                record.name
            )

            record_table_map[
                idms_record_name
            ] = canonical_record_name

        return record_table_map

    def _build_records_payload(
        self,
        db2_model: DB2Model
    ) -> list[dict[str, Any]]:

        records_payload: list[dict[str, Any]] = []

        for table in db2_model.tables:
            fields_payload = []

            for column in table.columns:
                datatype, length, scale = self._parse_db2_datatype(
                    column.datatype
                )

                fields_payload.append(
                    {
                        "name": column.name,
                        "column": column.name,
                        "datatype": datatype,
                        "length": length,
                        "scale": scale,
                        "nullable": column.nullable,
                        "primary_key": column.primary_key
                    }
                )

            records_payload.append(
                {
                    "name": table.name,
                    "table": table.name,
                    "primary_key": table.primary_key,
                    "fields": fields_payload
                }
            )

        return records_payload

    def _build_field_map(
        self,
        metadata: SchemaMetadata,
        canonical_schema: CanonicalSchema,
        db2_table_lookup: dict[str, DB2Table],
        record_table_map: dict[str, str]
    ) -> dict[str, dict[str, Any]]:

        field_map: dict[str, dict[str, Any]] = {}

        for record in metadata.records:
            idms_record_name = NameNormalizer.normalize(
                record.name
            )

            table_name = record_table_map.get(
                idms_record_name,
                idms_record_name
            )

            table = db2_table_lookup.get(
                table_name
            )

            if table is None:
                continue

            db2_columns = {
                NameNormalizer.normalize(column.name): column
                for column in table.columns
            }

            for field in record.fields:
                legacy_field_name = NameNormalizer.normalize(
                    field.name
                )

                physical_column_name = self._find_matching_column(
                    legacy_field_name=legacy_field_name,
                    db2_columns=db2_columns
                )

                if not physical_column_name:
                    continue

                host = self._host_variable(
                    record_name=idms_record_name,
                    column_name=physical_column_name,
                    remove_suffix=True
                )

                field_map[
                    legacy_field_name
                ] = {
                    "host": host,
                    "record": idms_record_name,
                    "table": table.name,
                    "column": physical_column_name,
                    "legacy_field": legacy_field_name
                }

                suffix_removed_legacy = self._remove_record_suffix(
                    legacy_field_name
                )

                field_map[
                    suffix_removed_legacy
                ] = {
                    "host": host,
                    "record": idms_record_name,
                    "table": table.name,
                    "column": physical_column_name,
                    "legacy_field": legacy_field_name
                }

        return field_map

    def _build_calc_key_map(
        self,
        canonical_schema: CanonicalSchema,
        metadata: SchemaMetadata,
        record_table_map: dict[str, str]
    ) -> dict[str, dict[str, Any]]:

        calc_key_map: dict[str, dict[str, Any]] = {}

        for record in metadata.records:
            if not record.primary_key:
                continue

            idms_record_name = NameNormalizer.normalize(
                record.name
            )

            table_name = record_table_map.get(
                idms_record_name,
                idms_record_name
            )

            primary_key = NameNormalizer.normalize(
                record.primary_key
            )

            calc_key_map[
                idms_record_name
            ] = {
                "record": idms_record_name,
                "table": table_name,
                "key": primary_key,
                "host": self._host_variable(
                    record_name=idms_record_name,
                    column_name=primary_key,
                    remove_suffix=True
                )
            }

        for record in canonical_schema.records:
            if not record.primary_key:
                continue

            record_name = NameNormalizer.normalize(
                record.name
            )

            primary_key = NameNormalizer.normalize(
                record.primary_key
            )

            calc_key_map[
                record_name
            ] = {
                "record": record_name,
                "table": record_name,
                "key": primary_key,
                "host": self._host_variable(
                    record_name=record_name,
                    column_name=primary_key,
                    remove_suffix=True
                )
            }

        return calc_key_map

    def _build_relationships_payload(
        self,
        canonical_schema: CanonicalSchema,
        db2_table_lookup: dict[str, DB2Table]
    ) -> list[dict[str, Any]]:

        relationships_payload: list[dict[str, Any]] = []

        for relationship in canonical_schema.relationships:
            parent_record = NameNormalizer.normalize(
                relationship.parent_record
            )

            child_record = NameNormalizer.normalize(
                relationship.child_record
            )

            set_name = NameNormalizer.normalize(
                relationship.set_name
            )

            parent_table = db2_table_lookup.get(
                parent_record
            )

            child_table = db2_table_lookup.get(
                child_record
            )

            parent_key = None
            child_fk = None
            order_by = []

            if parent_table is not None:
                parent_key = parent_table.primary_key

            if (
                child_table is not None
                and parent_key is not None
            ):
                child_column_names = {
                    NameNormalizer.normalize(column.name)
                    for column in child_table.columns
                }

                if parent_key in child_column_names:
                    child_fk = parent_key
                    order_by = [
                        child_fk
                    ]

            relationships_payload.append(
                {
                    "set_name": set_name,
                    "parent_record": parent_record,
                    "child_record": child_record,
                    "parent_key": parent_key,
                    "child_fk": child_fk,
                    "cardinality": relationship.cardinality or "1:N",
                    "order_by": order_by
                }
            )

        return relationships_payload

    def _build_set_ordering_map(
        self,
        relationships_payload: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:

        set_ordering_map: dict[str, dict[str, Any]] = {}

        for relationship in relationships_payload:
            set_name = relationship.get(
                "set_name"
            )

            order_by = relationship.get(
                "order_by"
            ) or []

            if not set_name:
                continue

            set_ordering_map[
                set_name
            ] = {
                "order_by": order_by
            }

        return set_ordering_map

    def _build_nullable_fk_map(
        self,
        db2_model: DB2Model
    ) -> dict[str, bool]:

        nullable_fk_map: dict[str, bool] = {}

        for table in db2_model.tables:
            column_lookup = {
                column.name: column
                for column in table.columns
            }

            for foreign_key in table.foreign_keys:
                fk_column = column_lookup.get(
                    foreign_key.column_name
                )

                nullable_fk_map[
                    f"{table.name}.{foreign_key.column_name}"
                ] = (
                    fk_column.nullable
                    if fk_column is not None
                    else True
                )

        return nullable_fk_map

    def _build_date_part_map(
        self,
        metadata: SchemaMetadata,
        canonical_schema: CanonicalSchema,
        db2_table_lookup: dict[str, DB2Table],
        record_table_map: dict[str, str]
    ) -> dict[str, dict[str, Any]]:

        date_part_map: dict[str, dict[str, Any]] = {}

        for record in metadata.records:
            idms_record_name = NameNormalizer.normalize(
                record.name
            )

            table_name = record_table_map.get(
                idms_record_name,
                idms_record_name
            )

            table = db2_table_lookup.get(
                table_name
            )

            if table is None:
                continue

            date_columns = {
                NameNormalizer.normalize(column.name)
                for column in table.columns
                if column.datatype.upper() == "DATE"
            }

            for field in record.fields:
                legacy_field_name = NameNormalizer.normalize(
                    field.name
                )

                date_part = self._date_part_name(
                    legacy_field_name
                )

                if date_part is None:
                    continue

                physical_date_column = self._date_column_for_part(
                    legacy_field_name=legacy_field_name,
                    date_part=date_part
                )

                if physical_date_column not in date_columns:
                    continue

                date_part_meta = self.DATE_PARTS[
                    date_part
                ]

                date_part_map[
                    legacy_field_name
                ] = {
                    "host": self._host_variable(
                        record_name=idms_record_name,
                        column_name=physical_date_column,
                        remove_suffix=True
                    ),
                    "table": table.name,
                    "column": physical_date_column,
                    "date_part": date_part,
                    "substring_start": date_part_meta["substring_start"],
                    "substring_length": date_part_meta["substring_length"]
                }

        return date_part_map

    def _build_navigation_intent(
        self,
        relationships_payload: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:

        navigation_intent: dict[str, dict[str, Any]] = {}

        for relationship in relationships_payload:
            set_name = relationship.get(
                "set_name"
            )

            if not set_name:
                continue

            navigation_intent[
                set_name
            ] = {
                "access_pattern": "SET_NAVIGATION",
                "parent_record": relationship.get("parent_record"),
                "child_record": relationship.get("child_record"),
                "parent_key": relationship.get("parent_key"),
                "child_fk": relationship.get("child_fk"),
                "order_by": relationship.get("order_by") or []
            }

        return navigation_intent

    def _build_output_semantics(
        self
    ) -> dict[str, Any]:

        return {
            "generated_by": "idms-db2-modernizer-phase1",
            "usage": "IDMS retrieval COBOL to DB2 embedded SQL conversion",
            "physical_types_source": "DB2_DDL",
            "logical_mapping_source": "PHASE1_CANONICAL_METADATA"
        }

    def _build_validation_messages(
        self,
        canonical_schema: CanonicalSchema,
        db2_model: DB2Model,
        metadata: SchemaMetadata,
        field_map: dict[str, dict[str, Any]]
    ) -> list[str]:

        messages: list[str] = []

        if not canonical_schema.records:
            messages.append(
                "No canonical records found."
            )

        if not db2_model.tables:
            messages.append(
                "No DB2 tables found."
            )

        if not metadata.records:
            messages.append(
                "No IDMS metadata records found."
            )

        if not field_map:
            messages.append(
                "No field_map entries generated."
            )

        decimal_warning_count = 0

        for table in db2_model.tables:
            for column in table.columns:
                datatype = column.datatype.upper()

                if datatype.startswith("DECIMAL(18,0)"):
                    decimal_warning_count += 1

        if decimal_warning_count:
            messages.append(
                f"{decimal_warning_count} DECIMAL(18,0) columns detected. "
                "Review COMP-3 precision and scale extraction."
            )

        return messages

    def _find_matching_column(
        self,
        legacy_field_name: str,
        db2_columns: dict[str, DB2Column]
    ) -> str | None:

        normalized = NameNormalizer.normalize(
            legacy_field_name
        )

        if normalized in db2_columns:
            return normalized

        suffix_removed = self._remove_record_suffix(
            normalized
        )

        for column_name in db2_columns:
            if self._remove_record_suffix(column_name) == suffix_removed:
                return column_name

        return None

    def _date_part_name(
        self,
        field_name: str
    ) -> str | None:

        normalized = NameNormalizer.normalize(
            field_name
        )

        parts = normalized.split("_")

        if len(parts) < 3:
            return None

        for part in self.DATE_PARTS:
            if f"_{part}_" in normalized:
                return part

        return None

    def _date_column_for_part(
        self,
        legacy_field_name: str,
        date_part: str
    ) -> str:

        normalized = NameNormalizer.normalize(
            legacy_field_name
        )

        return normalized.replace(
            f"_{date_part}_",
            "_DATE_"
        )

    def _host_variable(
        self,
        record_name: str,
        column_name: str,
        remove_suffix: bool = True
    ) -> str:

        record = NameNormalizer.normalize(
            record_name
        ).replace(
            "_",
            "-"
        )

        column = NameNormalizer.normalize(
            column_name
        )

        if remove_suffix:
            column = self._remove_record_suffix(
                column
            )

        column = column.replace(
            "_",
            "-"
        )

        return f"HV-{record}-{column}"

    def _remove_record_suffix(
        self,
        name: str
    ) -> str:

        normalized = NameNormalizer.normalize(
            name
        )

        parts = normalized.split("_")

        if (
            len(parts) > 1
            and parts[-1].isdigit()
            and len(parts[-1]) == 4
        ):
            return "_".join(
                parts[:-1]
            )

        return normalized

    def _parse_db2_datatype(
        self,
        datatype: str
    ) -> tuple[str, int | None, int | None]:

        value = (
            datatype
            or "VARCHAR(255)"
        ).strip().upper()

        decimal_match = re.match(
            r"^(DECIMAL|NUMERIC)$(\d+),\s*(\d+)$$",
            value
        )

        if decimal_match:
            return (
                "DECIMAL",
                int(decimal_match.group(2)),
                int(decimal_match.group(3))
            )

        varchar_match = re.match(
            r"^(VARCHAR|CHAR)$(\d+)$$",
            value
        )

        if varchar_match:
            return (
                varchar_match.group(1),
                int(varchar_match.group(2)),
                None
            )

        if value in {
            "SMALLINT"
        }:
            return (
                "SMALLINT",
                4,
                0
            )

        if value in {
            "INTEGER",
            "INT"
        }:
            return (
                "INTEGER",
                9,
                0
            )

        if value == "BIGINT":
            return (
                "BIGINT",
                18,
                0
            )

        if value == "DATE":
            return (
                "DATE",
                None,
                None
            )

        if value == "TIMESTAMP":
            return (
                "TIMESTAMP",
                None,
                None
            )

        return (
            value,
            None,
            None
        )