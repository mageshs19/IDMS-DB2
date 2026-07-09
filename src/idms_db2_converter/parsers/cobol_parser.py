import re

from idms_db2_converter.models import CobolAnalysis, Paragraph


class CobolParser:
    """
    Parses IDMS COBOL.

    Captures:
    - PROGRAM-ID
    - COPY IDMS RECORD usage
    - OBTAIN CALC record usage
    - OBTAIN NEXT record WITHIN set
    - OBTAIN OWNER WITHIN set
    - FIND FIRST WITHIN set
    - STORE record usage
    - MODIFY record usage
    - ERASE record usage
    - READY AREA ... USAGE-MODE IS UPDATE
    - Paragraphs
    - IDMS schema-suffixed field references in PROCEDURE DIVISION

    Important:
    - This parser does not hard-code record suffix to record-name mappings.
    - Record/field inference should come from schema metadata, not from demo data.
    """

    PROGRAM_ID = re.compile(
        r"^\s*PROGRAM-ID\.\s*([A-Z0-9-]+)\.?",
        re.IGNORECASE | re.MULTILINE,
    )

    COPY_RECORD = re.compile(
        r"^\s*(?:01\s+)?COPY\s+IDMS\s+RECORD\s+([A-Z0-9-]+)\.?",
        re.IGNORECASE | re.MULTILINE,
    )

    OBTAIN_CALC = re.compile(
        r"^\s*OBTAIN\s+CALC\s+([A-Z0-9-]+)\.?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    OBTAIN_NEXT = re.compile(
        r"^\s*OBTAIN\s+NEXT\s+([A-Z0-9-]+)\s+WITHIN\s+([A-Z0-9-]+)\.?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    OBTAIN_OWNER = re.compile(
        r"^\s*OBTAIN\s+OWNER\s+WITHIN\s+([A-Z0-9-]+)\.?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    FIND_FIRST = re.compile(
        r"^\s*FIND\s+FIRST\s+WITHIN\s+([A-Z0-9-]+)\.?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    STORE_RECORD = re.compile(
        r"^\s*STORE\s+([A-Z0-9-]+)\.?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    MODIFY_RECORD = re.compile(
        r"^\s*MODIFY\s+([A-Z0-9-]+)\.?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    ERASE_RECORD = re.compile(
        r"^\s*ERASE\s+([A-Z0-9-]+)\.?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    READY_UPDATE_AREA = re.compile(
        r"""
        ^\s*READY\s+AREA\s+([A-Z0-9-]+)\.?\s*
        (?:\n\s*USAGE-MODE\s+IS\s+UPDATE\.?\s*)?
        """,
        re.IGNORECASE | re.MULTILINE | re.VERBOSE,
    )

    PARAGRAPH_HEADER = re.compile(
        r"^\s*([A-Z0-9-]+)\.\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    IDMS_SCHEMA_FIELD = re.compile(
        r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d{4}\b",
        re.IGNORECASE,
    )

    PROCEDURE_DIVISION = re.compile(
        r"^\s*PROCEDURE\s+DIVISION\.\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    def parse(
        self,
        cobol: str,
    ) -> CobolAnalysis:
        source = self.remove_comment_lines(
            cobol,
        )

        program_match = self.PROGRAM_ID.search(
            source,
        )

        analysis = CobolAnalysis(
            program_id=self._upper_or_none(
                program_match.group(1)
                if program_match
                else None
            ),
            idms_records=self._unique(
                self.COPY_RECORD.findall(source),
            ),
            obtain_calc_records=self._unique(
                self.OBTAIN_CALC.findall(source),
            ),
            obtain_next=[
                (
                    record.upper(),
                    set_name.upper(),
                )
                for record, set_name in self.OBTAIN_NEXT.findall(source)
            ],
            obtain_owner_sets=self._unique(
                self.OBTAIN_OWNER.findall(source),
            ),
            find_first_sets=self._unique(
                self.FIND_FIRST.findall(source),
            ),
            store_records=self._unique(
                self.STORE_RECORD.findall(source),
            ),
            modify_records=self._unique(
                self.MODIFY_RECORD.findall(source),
            ),
            erase_records=self._unique(
                self.ERASE_RECORD.findall(source),
            ),
            ready_update_areas=self._unique(
                self.READY_UPDATE_AREA.findall(source),
            ),
        )

        self._attach_field_references(
            analysis=analysis,
            cobol=source,
        )

        return analysis

    def paragraphs(
        self,
        cobol: str,
    ) -> list[Paragraph]:
        source = self.remove_comment_lines(
            cobol,
        )

        matches = list(
            self.PARAGRAPH_HEADER.finditer(source),
        )

        paragraphs: list[Paragraph] = []

        for index, match in enumerate(matches):
            name = match.group(1).upper()
            start = match.start()

            if index + 1 < len(matches):
                end = matches[index + 1].start()
            else:
                end = len(source)

            paragraphs.append(
                Paragraph(
                    name=name,
                    text=source[start:end],
                )
            )

        return paragraphs

    def remove_comment_lines(
        self,
        cobol: str,
    ) -> str:
        lines: list[str] = []

        for line in cobol.splitlines():
            stripped = line.strip()

            if not stripped:
                lines.append(line)
                continue

            if stripped.startswith("*"):
                continue

            lines.append(line)

        return "\n".join(lines)

    def _attach_field_references(
        self,
        analysis: CobolAnalysis,
        cobol: str,
    ) -> None:
        procedure_text = self._procedure_division_text(
            cobol,
        )

        field_references = self._unique(
            self.IDMS_SCHEMA_FIELD.findall(
                procedure_text,
            )
        )

        try:
            analysis.field_references = field_references
        except Exception:
            pass

        try:
            analysis.idms_fields = field_references
        except Exception:
            pass

        record_names = set(
            analysis.idms_records,
        )

        for record in analysis.obtain_calc_records:
            record_names.add(
                record,
            )

        for record, _ in analysis.obtain_next:
            record_names.add(
                record,
            )

        for record in getattr(
            analysis,
            "store_records",
            [],
        ):
            record_names.add(
                record,
            )

        for record in getattr(
            analysis,
            "modify_records",
            [],
        ):
            record_names.add(
                record,
            )

        for record in getattr(
            analysis,
            "erase_records",
            [],
        ):
            record_names.add(
                record,
            )

        try:
            analysis.idms_records = sorted(
                record_names,
            )
        except Exception:
            pass

    def _procedure_division_text(
        self,
        cobol: str,
    ) -> str:
        match = self.PROCEDURE_DIVISION.search(
            cobol,
        )

        if not match:
            return cobol

        return cobol[match.start():]

    def _unique(
        self,
        values,
    ) -> list[str]:
        seen = set()
        result: list[str] = []

        for value in values:
            upper_value = value.upper()

            if upper_value not in seen:
                seen.add(
                    upper_value,
                )

                result.append(
                    upper_value,
                )

        return result

    def _upper_or_none(
        self,
        value: str | None,
    ) -> str | None:
        return value.upper() if value else None