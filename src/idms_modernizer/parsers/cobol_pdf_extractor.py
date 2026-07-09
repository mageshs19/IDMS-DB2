import re
import pdfplumber


class CobolPdfExtractor:
    """
    Extracts COBOL text from PDF.

    Supports:
    - COBOL pasted as text in PDF
    - line-preserving extraction
    - fallback to empty string if extraction fails
    """

    def extract_text(
        self,
        pdf_path: str
    ) -> str:

        lines: list[str] = []

        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = (
                    page.extract_text()
                    or ""
                )

                for raw_line in page_text.splitlines():
                    cleaned_line = self._clean_line(
                        raw_line
                    )

                    lines.append(
                        cleaned_line
                    )

        return "\n".join(lines).strip()

    def _clean_line(
        self,
        line: str | None
    ) -> str:

        if line is None:
            return ""

        cleaned = str(line).rstrip()

        cleaned = cleaned.replace(
            "\t",
            " "
        )

        cleaned = re.sub(
            r"[ \u00A0]+",
            " ",
            cleaned
        )

        return cleaned