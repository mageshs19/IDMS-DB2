import re

from idms_modernizer.parsers.text_extractor import TextExtractor
from idms_modernizer.services.document_segmenter import DocumentSegmenter
from idms_modernizer.extractors.owner_member_extractor import OwnerMemberExtractor
from idms_modernizer.extractors.field_extractor import FieldExtractor
from idms_modernizer.extractors.cobol_zone_extractor import CobolZoneExtractor
from idms_modernizer.services.schema_picture_enricher import SchemaPictureEnricher
from idms_modernizer.services.relationship_resolver import RelationshipResolver
from idms_modernizer.domain.schema_models import SchemaMetadata, Record
from idms_modernizer.extractors.primary_key_extractor import PrimaryKeyExtractor


print("LOADED MetadataService VERSION GENERIC-DEBUG-NO-FIELD-HARDCODE-2026-07-30")


class MetadataService:
    """
    Builds SchemaMetadata from the schema PDF.

    Critical rule:
    - record.fields is used for physical DB2 / DDL / canonical schema.
    - record.mapping_fields is used for Excel Sheet Mapping.
    - BOTH must be enriched with:
      - PIC clause
      - datatype
      - length
      - scale
      - start_position
      - end_position
      - basetype

    Generic behavior:
    - No hardcoded record names.
    - No hardcoded field names.
    - No hardcoded business/application field names.
    - Debug logging is pattern-based, not field-name based.

    Notes:
    - Date identification should remain token/pattern based in downstream services.
    - Date tokens such as YEAR, MONTH, DAY, YY, MM, DD, DA, DATE are generic schema concepts,
      not application-specific field hardcoding.
    """

    DEBUG = True

    FIELD_LINE_PATTERN = re.compile(
        r"^\s*(0[1-9]|[1-4][0-9]|88)\s+([A-Z][A-Z0-9-]*|FILLER)\b",
        re.IGNORECASE,
    )

    PIC_OR_USAGE_PATTERN = re.compile(
        r"\b(PIC|PICTURE|DISPLAY|COMP-3|COMP)\b",
        re.IGNORECASE,
    )

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
        print("USING MetadataService.build_metadata VERSION GENERIC-DEBUG-NO-FIELD-HARDCODE-2026-07-30")

        document = self.extractor.extract_document(
            pdf_path,
        )

        sections = self.segmenter.segment(
            document,
        )

        if self.DEBUG:
            print(
                "METADATA_DOCUMENT_DEBUG",
                f"sections_count={len(sections or [])}",
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

            if self.DEBUG:
                print("=" * 100)
                print(f"METADATA DEBUG RECORD: {record.name}")
                print("=" * 100)
                print(f"RAW SECTION LINE COUNT: {len(section.lines or [])}")
                print(f"PHYSICAL FIELD COUNT BEFORE ENRICH: {len(physical_fields or [])}")
                print(f"MAPPING FIELD COUNT BEFORE ENRICH: {len(mapping_fields or [])}")

                self.print_generic_raw_schema_lines(
                    record_name=record.name,
                    lines=section.lines,
                )

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

            if self.DEBUG:
                print("=" * 100)
                print(f"FIELDS EXTRACTED FOR {record.name} - PHYSICAL")
                print("=" * 100)

                for field in record.fields or []:
                    self.print_field_debug(
                        label="PHYSICAL_FIELD_DEBUG",
                        field=field,
                    )

                print("=" * 100)
                print(f"FIELDS EXTRACTED FOR {record.name} - MAPPING")
                print("=" * 100)

                for field in record.mapping_fields or []:
                    self.print_field_debug(
                        label="MAPPING_FIELD_DEBUG",
                        field=field,
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

        if self.DEBUG:
            print(
                f"Relationships Found: {len(metadata.relationships)}"
            )

        return metadata

    def print_generic_raw_schema_lines(
        self,
        record_name: str,
        lines,
    ) -> None:
        """
        Generic raw-line debug.

        This replaces hardcoded target_tokens.

        Prints:
        - COBOL/IDMS data item lines such as 02 FIELD-NAME, 04 FIELD-NAME, etc.
        - Lines containing PIC / PICTURE / DISPLAY / COMP / COMP-3.

        This is generic and works for any schema listing.
        """

        print("=" * 100)
        print(f"RAW GENERIC SCHEMA LINES FOR {record_name}")
        print("=" * 100)

        for index, line in enumerate(lines or []):
            value = getattr(line, "text", None)

            if value is None:
                value = str(line)

            text = str(value or "").strip()

            if not text:
                continue

            is_field_line = self.FIELD_LINE_PATTERN.search(text) is not None
            is_pic_or_usage_line = self.PIC_OR_USAGE_PATTERN.search(text) is not None

            if is_field_line or is_pic_or_usage_line:
                print(
                    "METADATA_RAW_SCHEMA_LINE",
                    f"record={record_name}",
                    f"index={index}",
                    f"line={repr(text)}",
                )

    def print_field_debug(
        self,
        label: str,
        field,
    ) -> None:
        print(
            label,
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