from idms_modernizer.parsers.text_extractor import TextExtractor
from idms_modernizer.services.document_segmenter import DocumentSegmenter
from idms_modernizer.extractors.owner_member_extractor import OwnerMemberExtractor
from idms_modernizer.extractors.field_extractor import FieldExtractor
from idms_modernizer.extractors.cobol_zone_extractor import CobolZoneExtractor
from idms_modernizer.services.schema_picture_enricher import SchemaPictureEnricher
from idms_modernizer.services.relationship_resolver import RelationshipResolver
from idms_modernizer.domain.schema_models import SchemaMetadata, Record
from idms_modernizer.extractors.primary_key_extractor import PrimaryKeyExtractor


print("LOADED MetadataService VERSION ENRICH-FIELDS-AND-MAPPING-FIELDS-2026-07-29")


class MetadataService:
    """
    Builds SchemaMetadata from the schema PDF.

    Important:
    - record.fields is used for physical DB2 / DDL.
    - record.mapping_fields is used for Excel Sheet Mapping.
    - Both must be enriched with:
      - PIC clause
      - datatype
      - length
      - scale
      - start_position
      - end_position
      - basetype

    Root cause fixed:
    Previously only record.fields was enriched. Excel uses mapping_fields,
    so IDMS PIC Clause was blank for many rows.
    """

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
        print("USING MetadataService.build_metadata VERSION ENRICH-FIELDS-AND-MAPPING-FIELDS-2026-07-29")

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

            physical_fields = self.field_extractor.extract(
                section.lines,
            )

            mapping_fields = self.field_extractor.extract_all(
                section.lines,
                include_filler=True,
            )

            print("=" * 100)
            print(f"METADATA DEBUG RECORD: {record.name}")
            print("=" * 100)
            print(f"RAW SECTION LINE COUNT: {len(section.lines or [])}")
            print(f"PHYSICAL FIELD COUNT BEFORE ENRICH: {len(physical_fields or [])}")
            print(f"MAPPING FIELD COUNT BEFORE ENRICH: {len(mapping_fields or [])}")

            record.fields = self.picture_enricher.enrich(
                fields=physical_fields,
                lines=section.lines,
                debug_label=f"{record.name} PHYSICAL",
            )

            record.mapping_fields = self.picture_enricher.enrich(
                fields=mapping_fields,
                lines=section.lines,
                debug_label=f"{record.name} MAPPING",
            )

            record.set_memberships = self.membership_extractor.extract(
                section.record_name,
                section.lines,
            )

            record.primary_key = self.primary_key_extractor.extract(
                section.lines,
            )

            print("=" * 100)
            print(f"FIELDS EXTRACTED FOR {record.name} - PHYSICAL")
            print("=" * 100)

            for field in record.fields:
                print(
                    "PHYSICAL_FIELD_DEBUG",
                    "name=", getattr(field, "name", None),
                    "level=", getattr(field, "level", None),
                    "datatype=", getattr(field, "datatype", None),
                    "length=", getattr(field, "length", None),
                    "scale=", getattr(field, "scale", None),
                    "picture=", getattr(field, "picture", None),
                    "start=", getattr(field, "start_position", None),
                    "end=", getattr(field, "end_position", None),
                    "basetype=", getattr(field, "basetype", None),
                    "group=", getattr(field, "is_group", None),
                    "has_child=", getattr(field, "has_child", None),
                )

            print("=" * 100)
            print(f"FIELDS EXTRACTED FOR {record.name} - MAPPING")
            print("=" * 100)

            for field in record.mapping_fields:
                print(
                    "MAPPING_FIELD_DEBUG",
                    "name=", getattr(field, "name", None),
                    "level=", getattr(field, "level", None),
                    "datatype=", getattr(field, "datatype", None),
                    "length=", getattr(field, "length", None),
                    "scale=", getattr(field, "scale", None),
                    "picture=", getattr(field, "picture", None),
                    "start=", getattr(field, "start_position", None),
                    "end=", getattr(field, "end_position", None),
                    "basetype=", getattr(field, "basetype", None),
                    "group=", getattr(field, "is_group", None),
                    "has_child=", getattr(field, "has_child", None),
                )

            print(
                f"MetadataService: {record.name} "
                f"PK={record.primary_key} "
                f"ZONE={record.cobol_zone} "
                f"PHYSICAL_FIELDS={len(record.fields or [])} "
                f"MAPPING_FIELDS={len(record.mapping_fields or [])}"
            )

            metadata.records.append(record)

        metadata.relationships = self.relationship_resolver.resolve(
            metadata,
        )

        print(
            f"Relationships Found: {len(metadata.relationships)}"
        )

        return metadata