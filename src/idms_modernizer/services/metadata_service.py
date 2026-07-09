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

            discovered_fields = self.field_extractor.extract(
                section.lines,
            )

            record.fields = self.picture_enricher.enrich(
                fields=discovered_fields,
                lines=section.lines,
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