import re

from idms_modernizer.domain.document_models import (
    DocumentModel
)

from idms_modernizer.domain.schema_models import (
    DataField,
    Record,
    SchemaMetadata,
)


class MetadataBuilder:

    RECORD_PATTERN = re.compile(
        r"RECORD\s+NAME.*?([A-Z][A-Z0-9\-]+)",
        re.IGNORECASE
    )

    FIELD_PATTERN = re.compile(
        r"^\d{2}\s+([A-Z][A-Z0-9\-]+)",
        re.IGNORECASE
    )

    def build(
        self,
        document: DocumentModel
    ) -> SchemaMetadata:

        metadata = SchemaMetadata()

        current_record = None

        seen_records = set()

        for page in document.pages:

            for line in page.lines:

                text = line.text.strip()

                if not text:
                    continue

                #
                # RECORD DETECTION
                #

                record_match = (
                    self.RECORD_PATTERN.search(
                        text
                    )
                )

                if record_match:

                    record_name = (
                        record_match.group(1)
                        .strip()
                        .upper()
                    )

                    if (
                        record_name
                        not in seen_records
                    ):

                        current_record = Record(
                            name=record_name
                        )

                        metadata.records.append(
                            current_record
                        )

                        seen_records.add(
                            record_name
                        )

                    continue

                #
                # FIELD DETECTION
                #

                if current_record:

                    field_match = (
                        self.FIELD_PATTERN.match(
                            text
                        )
                    )

                    if field_match:

                        field_name = (
                            field_match.group(1)
                            .strip()
                            .upper()
                        )

                        current_record.fields.append(
                            DataField(
                                name=field_name
                            )
                        )

        #
        # DEBUG OUTPUT
        #

        print(
            "\n========== RECORDS =========="
        )

        for record in metadata.records:

            print(
                f"{record.name} -> "
                f"{len(record.fields)} fields"
            )

        print(
            "=============================\n"
        )

        return metadata