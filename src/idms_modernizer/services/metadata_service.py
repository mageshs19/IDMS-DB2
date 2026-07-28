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
    """
    Builds schema metadata from IDMS schema listing PDF.

    Generic behavior only:
    - No DB2 table names are hardcoded.
    - No DB2 column names are hardcoded.
    - No business record names are hardcoded.

    Important:
    - record.fields is physical / DDL-safe and excludes FILLER.
    - record.mapping_fields is Sheet Mapping-only and includes FILLER.
    - metadata.relationships must be assigned from RelationshipResolver.
    """

    def __init__(self):
        self.extractor = TextExtractor()
        self.segmenter = DocumentSegmenter()

        self.field_extractor = FieldExtractor(
            include_filler=False,
            auto_number_filler=False,
        )

        self.mapping_field_extractor = FieldExtractor(
            include_filler=True,
            auto_number_filler=True,
        )

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

            mapping_discovered_fields = self.mapping_field_extractor.extract_all(
                section.lines,
                include_filler=True,
            )

            record.fields = self.picture_enricher.enrich(
                fields=physical_discovered_fields,
                lines=section.lines,
            )

            record.mapping_fields = self.picture_enricher.enrich(
                fields=mapping_discovered_fields,
                lines=section.lines,
            )

            record.set_memberships = self.membership_extractor.extract(
                section.record_name,
                section.lines,
            )

            record.primary_key = self.primary_key_extractor.extract(
                section.lines,
            )

            metadata.records.append(
                record,
            )

        metadata.relationships = self.relationship_resolver.resolve(
            metadata,
        )

        return metadata