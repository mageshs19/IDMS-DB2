import re
import sys
from dataclasses import dataclass, asdict
from typing import List, Optional, Set


# ------------- PDF READER ------------- #
def read_pdf_lines(pdf_path: str) -> List[str]:
    """
    Extract text lines from a PDF file using pdfminer.six.
    Returns a list of lines.
    """
    try:
        from pdfminer.high_level import extract_text
    except ImportError as e:
        raise RuntimeError(
            "pdfminer.six is required. Install it with:\n\n"
            "    pip install pdfminer.six\n"
        ) from e

    text = extract_text(pdf_path) or ""
    # Split into lines while preserving basic line structure
    lines = text.splitlines()
    # Trim trailing spaces for consistency
    return [ln.rstrip("\r\n") for ln in lines]


# ------------- DATA TYPES ------------- #
@dataclass(frozen=True)
class DataField:
    name: str
    datatype: str
    length: Optional[int]
    scale: Optional[int]
    picture: str


# ------------- EXTRACTOR ------------- #
class FieldExtractor:
    """
    Robust parser for IDMS-like listing lines.

    - Extracts PICTURE regardless of position and with/without PIC/PICTURE keyword
    - Recognizes DISPLAY, COMP, COMP-3 in any order relative to PICTURE
    - Skips FILLER items by default (configurable)
    - Removes duplicate names
    - Maps:
      * X -> CHAR(1)
      * X(n) -> VARCHAR(n)
      * DISPLAY + 9/S9[/ (n)] -> INTEGER(length = digits)
      * COMP/COMP-3 + 9/S9[/ (n)] -> DECIMAL(precision = digits)
      * S9(n)V9(m)/9(n)V9(m) -> DECIMAL(precision = n+m, scale = m)
    """

    def __init__(
        self,
        require_explicit_length: bool = False,
        include_filler: bool = False,
        auto_number_filler: bool = True,
    ):
        self.require_explicit_length = require_explicit_length
        self.include_filler = include_filler
        self.auto_number_filler = auto_number_filler

    # Start: <level> <name>
    _R_START = re.compile(r"^\s*(\d{2})\s+([A-Z0-9\-]+)\b", re.IGNORECASE)

    # USAGE anywhere (allow "USAGE IS ...")
    _R_USAGE = re.compile(r"\b(?:USAGE\s+IS\s+)?(DISPLAY|COMP-3|COMP)\b", re.IGNORECASE)

    # PICTURE anywhere; optional PIC/PICTURE keyword; tolerate spaces; no trailing \b
    _R_PIC_ANYWHERE = re.compile(
        r"""
        (?:\b(?:PIC|PICTURE)\s*)?
        (
          S\s*9\s*$\s*\d+\s*$\s*V\s*9\s*$\s*\d+\s*$ |  # S9(n)V9(m) / 9(n)V9(m)
          S\s*9\s*$\s*\d+\s*$                         |  # S9(n)
          9\s*$\s*\d+\s*$                             |  # 9(n)
          S\s*9                                         |  # S9
          9                                             |  # 9
          X\s*$\s*\d+\s*$                             |  # X(n)
          X                                                # X
        )
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    # Helpers (operate on normalized picture like X(30), 9(7), S9(7)V9(2))
    _R_CHAR = re.compile(r"^X$(\d+)$$", re.IGNORECASE)                # X(n)
    _R_INT  = re.compile(r"^S?9(?:$(\d+)$)?$", re.IGNORECASE)         # 9 / 9(n) / S9 / S9(n)
    _R_DEC  = re.compile(r"^S?9$(\d+)$V9$(\d+)$$", re.IGNORECASE)   # S9(n)V9(m) / 9(n)V9(m)

    def extract(self, lines: List[str]) -> List[DataField]:
        seen: Set[str] = set()
        out: List[DataField] = []
        filler_idx = 0

        for raw in lines:
            line = raw.strip()
            if not line:
                continue

            m_start = self._R_START.match(line)
            if not m_start:
                continue

            _, name = m_start.groups()
            name_up = name.upper()

            # Handle FILLER items
            if name_up.startswith("FILLER"):
                if not self.include_filler:
                    continue
                if self.auto_number_filler:
                    filler_idx += 1
                    name_up = f"FILLER_{filler_idx}"

            if name_up in seen:
                continue

            # USAGE default to DISPLAY if absent
            m_usage = self._R_USAGE.search(line)
            usage = m_usage.group(1).upper() if m_usage else "DISPLAY"

            # PICTURE capture
            m_pic = self._R_PIC_ANYWHERE.search(line)
            if not m_pic:
                continue

            # Normalize: remove spaces inside the picture and uppercase
            pic = re.sub(r"\s+", "", m_pic.group(1).upper())

            # Optional filter: require explicit length (skip X, 9, S9)
            if self.require_explicit_length and pic in {"X", "9", "S9"}:
                continue

            dtype: str = "VARCHAR"
            length: Optional[int] = None
            scale: Optional[int] = None

            # Character
            if pic == "X":
                dtype, length = "CHAR", 1
            elif self._R_CHAR.fullmatch(pic):
                length = int(self._R_CHAR.fullmatch(pic).group(1))
                dtype = "VARCHAR"

            # Decimal with V
            elif self._R_DEC.fullmatch(pic):
                int_len, frac_len = map(int, self._R_DEC.fullmatch(pic).groups())
                length = int_len + frac_len
                scale = frac_len
                dtype = "DECIMAL"

            # Integer-like 9/S9 with optional (n)
            elif self._R_INT.fullmatch(pic):
                digits_str = self._R_INT.fullmatch(pic).group(1)
                digits = int(digits_str) if digits_str else 1
                length = digits
                dtype = "INTEGER" if usage == "DISPLAY" else "DECIMAL"
            else:
                # Unrecognized picture; skip
                continue

            seen.add(name_up)
            out.append(
                DataField(
                    name=name_up,
                    datatype=dtype,
                    length=length,
                    scale=scale,
                    picture=pic,
                )
            )

        return out


# ------------- DEMO (PDF PATH) ------------- #
if __name__ == "__main__":
    # Option A: Provide the PDF file path here (edit this string)
    pdf_path = r"C:\VSCode\idms-db2-modernizer-master\idms-db2-modernizer-master\src\idms_modernizer\data\IDMS_Schema_Listing.pdf"

    # Option B: Or pass the path as first CLI argument
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]

    # Read lines from PDF
    lines = read_pdf_lines(pdf_path)

    # Configure extractor as needed
    extractor = FieldExtractor(
        require_explicit_length=False,  # set True to skip X / 9 / S9 without (n)
        include_filler=False,           # set True to include FILLER items
        auto_number_filler=True
    )

    fields = extractor.extract(lines)
    for f in fields:
        print(asdict(f))