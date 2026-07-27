from idms_modernizer.parsers.text_extractor import (
    TextExtractor,
)
from idms_modernizer.services.document_segmenter import (
    DocumentSegmenter,
)
from idms_modernizer.extractors.owner_member_extractor import (
    OwnerMemberExtractor,
)
from idms_modernizer.extractors.field_extractor import (
    FieldExtractor,
)
from idms_modernizer.extractors.cobol_zone_extractor import (
    CobolZoneExtractor,
)
from idms_modernizer.services.schema_picture_enricher import (
    SchemaPictureEnricher,
)
from idms_modernizer.services.relationship_resolver import (
    RelationshipResolver,
)
from idms_modernizer.domain.schema_models import (
    SchemaMetadata,
    Record,
)
from idms_modernizer.extractors.primary_key_extractor import (
    PrimaryKeyExtractor,
)
from idms_modernizer.services.name_normalizer import (
    NameNormalizer,
)


class MetadataService:
    def __init__(self):
        self.extractor = TextExtractor()
        self.segmenter = DocumentSegmenter()

        self.field_extractor = FieldExtractor()
        self.picture_enricher = SchemaPictureEnricher()
        self.membership_extractor = OwnerMemberExtractor()
        self.zone_extractor = CobolZoneExtractor()

        self.relationship_resolver = RelationshipResolver()
        self.primary_key_extractor = PrimaryKeyExtractor()

    def build_metadata(
        self,
        pdf_path: str,
    ) -> SchemaMetadata:
        document = self.extractor.extract_document(
            pdf_path,
        )

        sections = self.segmenter.segment(
            document,
        )

        metadata = SchemaMetadata()

        for section in sections:
            record = Record(
                name=section.record_name,
            )

            record.cobol_zone = self.zone_extractor.extract(
                section.lines,
            )

            physical_discovered_fields = self.field_extractor.extract(
                section.lines,
            )

            mapping_discovered_fields = self.field_extractor.extract_all(
                section.lines,
            )

            record.fields = self.picture_enricher.enrich(
                fields=physical_discovered_fields,
                lines=section.lines,
            )

            enriched_mapping_fields = self.picture_enricher.enrich(
                fields=mapping_discovered_fields,
                lines=section.lines,
            )

            record.mapping_fields = self.merge_structural_metadata(
                enriched_fields=enriched_mapping_fields,
                source_fields=mapping_discovered_fields,
            )

            record.set_memberships = self.membership_extractor.extract(
                section.record_name,
                section.lines,
            )

            record.primary_key = self.primary_key_extractor.extract(
                section.lines,
            )

            print("=" * 80)
            print(f"FIELDS EXTRACTED FOR {record.name}")
            print("=" * 80)

            print("PHYSICAL FIELDS:")
            for field in record.fields:
                print(
                    field.name,
                    field.datatype,
                    field.length,
                    field.scale,
                    field.picture,
                    field.start_position,
                    field.end_position,
                    field.basetype,
                )

            print("MAPPING FIELDS:")
            for field in record.mapping_fields:
                print(
                    field.name,
                    "LEVEL=",
                    field.level,
                    "GROUP=",
                    field.is_group,
                    "OCCURS=",
                    field.occurs,
                    field.occurs_min,
                    field.occurs_max,
                )

            print(
                f"MetadataService: {record.name} "
                f"PK={record.primary_key} "
                f"ZONE={record.cobol_zone}"
            )

            metadata.records.append(
                record,
            )

        metadata.relationships = self.relationship_resolver.resolve(
            metadata,
        )

        print(
            f"Relationships Found: {len(metadata.relationships)}"
        )

        return metadata

    def merge_structural_metadata(
        self,
        enriched_fields,
        source_fields,
    ):
        source_lookup = {
            NameNormalizer.normalize(field.name): field
            for field in source_fields
            if field and field.name
        }

        merged_fields = []

        for enriched_field in enriched_fields:
            key = NameNormalizer.normalize(
                enriched_field.name,
            )

            source_field = source_lookup.get(
                key,
            )

            if source_field is None:
                merged_fields.append(
                    enriched_field,
                )
                continue

            merged_fields.append(
                enriched_field.model_copy(
                    update={
                        "level": getattr(source_field, "level", None),
                        "has_child": getattr(source_field, "has_child", False),
                        "is_group": getattr(source_field, "is_group", False),
                        "occurs": getattr(source_field, "occurs", False),
                        "occurs_min": getattr(source_field, "occurs_min", None),
                        "occurs_max": getattr(source_field, "occurs_max", None),
                        "raw_line": getattr(source_field, "raw_line", None),
                        "rest": getattr(source_field, "rest", None),
                    }
                )
            )

        return merged_fields