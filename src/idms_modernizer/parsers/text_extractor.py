import re
import pdfplumber

from idms_modernizer.domain.document_models import (
    DocumentLine,
    DocumentModel,
    DocumentPage
)


class TextExtractor:
    """
    Plain text PDF extractor.

    Important:
    - Uses only page.extract_text().
    - Does not use extract_tables().
    - Does not use extract_words().
    - This keeps the useful rows seen in your debug, such as:
      03 EMP-FIRST-NAME-0415 DISPLAY X(10) 5 10
    """

    def extract_document(
        self,
        pdf_path: str
    ) -> DocumentModel:

        pages: list[DocumentPage] = []

        with pdfplumber.open(pdf_path) as pdf:
            for page_index, page in enumerate(pdf.pages):
                text = (
                    page.extract_text()
                    or ""
                )

                lines: list[DocumentLine] = []

                for line_index, raw_line in enumerate(
                    text.splitlines()
                ):
                    cleaned_line = self._clean_line(
                        raw_line
                    )

                    if not cleaned_line:
                        continue

                    lines.append(
                        DocumentLine(
                            line_number=line_index,
                            text=cleaned_line
                        )
                    )

                pages.append(
                    DocumentPage(
                        page_number=page_index,
                        lines=lines
                    )
                )

        return DocumentModel(
            pages=pages
        )

    def _clean_line(
        self,
        line: str | None
    ) -> str:

        if not line:
            return ""

        cleaned = str(line).strip()

        cleaned = re.sub(
            r"<[^>]+>",
            " ",
            cleaned
        )

        cleaned = cleaned.replace(
            "&nbsp;",
            " "
        )

        cleaned = cleaned.replace(
            "\t",
            " "
        )

        cleaned = cleaned.replace(
            "|",
            " "
        )

        cleaned = re.sub(
            r"\s+",
            " ",
            cleaned
        )

        return cleaned.strip()