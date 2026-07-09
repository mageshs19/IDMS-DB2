import re

from idms_modernizer.domain.section_models import (
    RecordSection
)


class DocumentSegmenter:

    RECORD_PATTERN = re.compile(
        r"RECORD\s+NAME.*?([A-Z0-9\-]+)",
        re.IGNORECASE
    )

    def segment(
        self,
        document
    ) -> list[RecordSection]:

        sections = []

        current_section = None

        for page in document.pages:

            for line in page.lines:

                text = line.text.strip()

                record_match = (
                    self.RECORD_PATTERN.search(
                        text
                    )
                )

                if record_match:

                    if current_section:

                        sections.append(
                            current_section
                        )

                    current_section = (
                        RecordSection(
                            record_name=record_match.group(1),
                            lines=[]
                        )
                    )

                elif current_section:

                    current_section.lines.append(
                        text
                    )

        if current_section:

            sections.append(
                current_section
            )

        return sections