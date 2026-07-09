from copy import deepcopy
from time import perf_counter
from idms_db2_converter.exceptions import ConversionError
from idms_db2_converter.models import SchemaModel
from idms_db2_converter.parsers.cobol_parser import CobolParser
from idms_db2_converter.parsers.canonical_parser import CanonicalParser
from idms_db2_converter.parsers.ddl_parser import DDLParser
from idms_db2_converter.parsers.phase2_metadata_parser import Phase2MetadataParser
from idms_db2_converter.parsers.idms_schema_parser import IdmsSchemaParser
from idms_db2_converter.services.relationship_resolver import RelationshipResolver
from idms_db2_converter.services.schema_merger import SchemaMerger
from idms_db2_converter.transformers.retrieval_transformer import RetrievalTransformer
from idms_db2_converter.validators.output_validator import OutputValidator
from idms_db2_converter.validators.schema_validator import SchemaValidator


class ConversionService:
    DEBUG_SCHEMA = False

    def convert_retrieval(
        self,
        cobol_text: str,
        canonical_json: str,
        phase2_metadata_json: str | None = None,
        ddl_text: str | None = None,
        idms_schema_text: str | None = None,
        relationship_overrides_json: str | None = None,
        target_program: str | None = None,
    ) -> tuple[str, list[str]]:
        timings: list[str] = []
        total_start = perf_counter()
        step_start = perf_counter()

        def add_timing(
            label: str,
        ) -> None:
            nonlocal step_start

            elapsed = perf_counter() - step_start
            message = f"Phase 2 - {label}: {elapsed:.2f} seconds"

            print(
                message,
            )

            timings.append(
                message,
            )

            step_start = perf_counter()

        analysis = CobolParser().parse(
            cobol_text,
        )

        add_timing(
            "COBOL parse",
        )

        schema_builder = (
            getattr(
                self,
                "_build_schema_from_available_sources",
                None,
            )
            or getattr(
                self,
                "build_schema_from_available_sources",
            )
        )

        schema = schema_builder(
            canonical_json=canonical_json,
            phase2_metadata_json=phase2_metadata_json,
            ddl_text=ddl_text,
            idms_schema_text=idms_schema_text,
        )

        add_timing(
            "Build schema from available sources",
        )

        if self.DEBUG_SCHEMA:
            self.debug_schema(
                schema,
            )

        add_timing(
            "Debug schema",
        )

        if (
            relationship_overrides_json
            and relationship_overrides_json.strip()
        ):
            schema = RelationshipResolver().apply_overrides(
                schema=schema,
                relationship_overrides_json=relationship_overrides_json,
            )

        add_timing(
            "Apply relationship overrides",
        )

        schema = RelationshipResolver().resolve_cobol_sets(
            schema=schema,
            analysis=analysis,
        )

        add_timing(
            "Resolve COBOL sets",
        )

        schema_errors = SchemaValidator().validate(
            schema,
            analysis,
        )

        add_timing(
            "Schema validation",
        )

        if schema_errors:
            raise ConversionError(
                "\n".join(schema_errors),
            )

        converted = RetrievalTransformer(
            schema,
            analysis,
        ).transform(
            cobol=cobol_text,
            target_program=target_program,
        )

        add_timing(
            "Retrieval transformer",
        )

        output_errors = OutputValidator().validate(
            converted,
        )

        add_timing(
            "Output validation",
        )

        validation_messages = []

        validation_messages.extend(
            getattr(
                schema,
                "validation_messages",
                [],
            )
        )

        validation_messages.extend(
            output_errors,
        )

        total_elapsed = perf_counter() - total_start

        timings.append(
            f"Phase 2 - TOTAL: {total_elapsed:.2f} seconds",
        )

        print("=" * 80)
        print("PHASE 2 TIMINGS")
        print("=" * 80)

        for timing in timings:
            print(
                timing,
            )

        validation_messages.extend(
            timings,
        )

        return converted, validation_messages

    def _build_schema_from_available_sources(
        self,
        canonical_json: str | None,
        phase2_metadata_json: str | None,
        ddl_text: str | None,
        idms_schema_text: str | None,
    ) -> SchemaModel:
        canonical_has_text = bool(canonical_json and canonical_json.strip())
        metadata_has_text = bool(phase2_metadata_json and phase2_metadata_json.strip())
        ddl_has_text = bool(ddl_text and ddl_text.strip())
        idms_schema_has_text = bool(idms_schema_text and idms_schema_text.strip())

        canonical_schema = SchemaModel()
        metadata_schema = SchemaModel()
        ddl_schema = SchemaModel()
        idms_schema = SchemaModel()

        if canonical_has_text:
            canonical_schema = CanonicalParser().parse(canonical_json)
            canonical_schema.schema_source = "CANONICAL"

        if metadata_has_text:
            metadata_schema = Phase2MetadataParser().parse_as_schema(
                phase2_metadata_json
            )
            metadata_schema.schema_source = "PHASE2_METADATA"

        if ddl_has_text:
            ddl_schema = DDLParser().parse(ddl_text)

            if self._has_schema_objects(ddl_schema):
                ddl_schema.schema_source = "DDL"
            elif self._looks_like_idms_schema(ddl_text):
                idms_schema = IdmsSchemaParser().parse(ddl_text)
                idms_schema.schema_source = "IDMS_SCHEMA"
            elif "CREATE TABLE" in ddl_text.upper():
                raise ConversionError(
                    "DDL text was provided and contains CREATE TABLE, but no tables were parsed."
                )

        if idms_schema_has_text:
            idms_schema = IdmsSchemaParser().parse(idms_schema_text)
            idms_schema.schema_source = "IDMS_SCHEMA"

        if self._has_schema_objects(ddl_schema):
            base_schema = ddl_schema
            base_schema.schema_source = "DDL"

            if self._has_schema_objects(canonical_schema):
                base_schema = self._merge_non_physical_metadata(
                    physical_schema=base_schema,
                    overlay=canonical_schema,
                )

            if metadata_has_text:
                base_schema = Phase2MetadataParser().parse_into_schema(
                    text=phase2_metadata_json,
                    schema=base_schema,
                )

            if self._has_schema_objects(idms_schema):
                base_schema = SchemaMerger().merge_physical_with_idms(
                    physical_schema=base_schema,
                    idms_schema=idms_schema,
                )

            return base_schema

        if self._has_schema_objects(canonical_schema):
            base_schema = canonical_schema

            if metadata_has_text:
                base_schema = Phase2MetadataParser().parse_into_schema(
                    text=phase2_metadata_json,
                    schema=base_schema,
                )

            if self._has_schema_objects(idms_schema):
                base_schema = self._merge_schema(base_schema, idms_schema)

            return base_schema

        if self._has_schema_objects(metadata_schema):
            base_schema = metadata_schema

            if self._has_schema_objects(idms_schema):
                base_schema = self._merge_schema(base_schema, idms_schema)

            return base_schema

        if self._has_schema_objects(idms_schema):
            return idms_schema

        raise ConversionError(
            "No usable schema source found. Provide canonical model JSON, "
            "Phase 2 metadata JSON with records/relationships, DB2 DDL, "
            "or IDMS schema listing."
        )

    def _merge_schema(
        self,
        base: SchemaModel,
        overlay: SchemaModel,
    ) -> SchemaModel:
        merged = deepcopy(base)

        for record_name, overlay_record in overlay.records.items():
            if record_name in merged.records:
                merged.records[record_name].primary_key = (
                    overlay_record.primary_key
                    or merged.records[record_name].primary_key
                )

                for field_name, overlay_field in overlay_record.fields.items():
                    merged.records[record_name].fields[field_name] = overlay_field
            else:
                merged.records[record_name] = overlay_record

        for set_name, overlay_rel in overlay.relationships.items():
            if set_name not in merged.relationships:
                merged.relationships[set_name] = overlay_rel
                continue

            rel = merged.relationships[set_name]
            rel.parent_record = overlay_rel.parent_record or rel.parent_record
            rel.child_record = overlay_rel.child_record or rel.child_record
            rel.parent_key = overlay_rel.parent_key or rel.parent_key
            rel.child_fk = overlay_rel.child_fk or rel.child_fk
            rel.cardinality = overlay_rel.cardinality or rel.cardinality

            if overlay_rel.order_by:
                rel.order_by = overlay_rel.order_by

        self._merge_dict(merged.field_map, overlay.field_map)
        self._merge_dict(merged.record_table_map, overlay.record_table_map)
        self._merge_dict(merged.calc_key_map, overlay.calc_key_map)
        self._merge_dict(merged.set_ordering_map, overlay.set_ordering_map)
        self._merge_dict(merged.navigation_intent, overlay.navigation_intent)
        self._merge_dict(merged.nullable_fk_map, overlay.nullable_fk_map)
        self._merge_dict(merged.date_part_map, overlay.date_part_map)
        self._merge_dict(merged.output_semantics, overlay.output_semantics)
        self._merge_dict(
            merged.paragraph_operation_graph,
            overlay.paragraph_operation_graph,
        )

        if hasattr(merged, "validation_messages") and hasattr(
            overlay,
            "validation_messages",
        ):
            merged.validation_messages.extend(overlay.validation_messages)

        if not getattr(merged, "schema_source", None):
            merged.schema_source = getattr(overlay, "schema_source", None)

        return merged

    def _merge_non_physical_metadata(
        self,
        physical_schema: SchemaModel,
        overlay: SchemaModel,
    ) -> SchemaModel:
        merged = deepcopy(physical_schema)

        self._merge_dict(merged.field_map, overlay.field_map)

        for key, value in overlay.record_table_map.items():
            if key not in merged.record_table_map:
                merged.record_table_map[key] = value

        self._merge_dict(merged.calc_key_map, overlay.calc_key_map)
        self._merge_dict(merged.set_ordering_map, overlay.set_ordering_map)
        self._merge_dict(merged.navigation_intent, overlay.navigation_intent)
        self._merge_dict(merged.nullable_fk_map, overlay.nullable_fk_map)
        self._merge_dict(merged.date_part_map, overlay.date_part_map)
        self._merge_dict(merged.output_semantics, overlay.output_semantics)
        self._merge_dict(
            merged.paragraph_operation_graph,
            overlay.paragraph_operation_graph,
        )

        for set_name, relationship in overlay.relationships.items():
            if set_name not in merged.relationships:
                merged.relationships[set_name] = relationship

        if hasattr(merged, "validation_messages") and hasattr(
            overlay,
            "validation_messages",
        ):
            merged.validation_messages.extend(overlay.validation_messages)

        merged.schema_source = "DDL+CANONICAL_METADATA"

        return merged

    def _merge_dict(self, target: dict, source: dict) -> None:
        for key, value in source.items():
            target[key] = value

    def _has_schema_objects(self, schema: SchemaModel) -> bool:
        if hasattr(schema, "has_schema_objects"):
            return schema.has_schema_objects()

        return bool(schema.records or schema.relationships)

    def _looks_like_idms_schema(self, text: str | None) -> bool:
        if not text:
            return False

        upper = text.upper()

        return (
            "RECORD NAME" in upper
            and "DBKEY POSITIONS" in upper
            and "DATA ITEM" in upper
        )

    def _debug_schema(self, schema: SchemaModel) -> None:
        print("FINAL SCHEMA SOURCE:", getattr(schema, "schema_source", None))
        print("RECORD COUNT:", len(schema.records))
        print("RELATIONSHIP COUNT:", len(schema.relationships))
        print("RECORD TABLE MAP COUNT:", len(schema.record_table_map))
        print("FIELD MAP COUNT:", len(schema.field_map))
        print("DATE PART MAP COUNT:", len(schema.date_part_map))

        for record_name in sorted(schema.records.keys()):
            record = schema.records[record_name]
            print(f"RECORD: {record_name} PK={record.primary_key}")

            for field_name in sorted(record.fields.keys()):
                field = record.fields[field_name]
                print(
                    "  FIELD:",
                    field_name,
                    field.datatype,
                    field.length,
                    field.scale,
                    "NULLABLE=",
                    field.nullable,
                )

        print("RELATIONSHIPS:")

        for set_name in sorted(schema.relationships.keys()):
            rel = schema.relationships[set_name]
            print(
                "  REL:",
                set_name,
                rel.parent_record,
                rel.parent_key,
                "->",
                rel.child_record,
                rel.child_fk,
            )