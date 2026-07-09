import re
from dataclasses import dataclass
from typing import List, Set

from idms_modernizer.domain.schema_models import DataField


@dataclass
class FieldCandidate:
    level: int
    name: str
    rest: str
    original_line: str
    has_child: bool = False


class FieldExtractor:
    """
    Discovers IDMS schema fields from record-section lines.

    Important behavior:
    - Identifies field candidates with COBOL level numbers.
    - Skips FILLER.
    - Skips level 88 condition names.
    - Skips group / outer fields that have subordinate child fields.
    - Returns only leaf / inner fields.

    Example:

        02 EMP-NAME-0415
        03 EMP-FIRST-NAME-0415 DISPLAY X(10) 1 10
        03 EMP-LAST-NAME-0415  DISPLAY X(15) 11 15

    Result:
        EMP-FIRST-NAME-0415
        EMP-LAST-NAME-0415

    Skipped:
        EMP-NAME-0415
    """

    FIELD_NAME_PATTERN = re.compile(
        r"^\s*(?P<level>0[1-9]|[1-4][0-9]|88)\s+"
        r"(?P<name>[A-Z][A-Z0-9-]*|FILLER)\b"
        r"(?P<rest>.*)$",
        re.IGNORECASE,
    )

    USAGE_PATTERN = re.compile(
        r"\b(DISPLAY|COMP-3|COMP)\b",
        re.IGNORECASE,
    )

    def extract(
        self,
        lines: List[str],
    ) -> List[DataField]:
        print("USING FIELD EXTRACTOR VERSION LEAF-ONLY-2026-07-08")

        candidates = self._discover_candidates(lines)
        leaf_candidates = self._mark_and_filter_leaf_fields(candidates)

        fields: List[DataField] = []
        seen: Set[str] = set()

        for candidate in leaf_candidates:
            name = candidate.name.upper()

            if name in seen:
                continue

            seen.add(name)
            fields.append(DataField(name=name))

        return fields

    def _discover_candidates(
        self,
        lines: List[str],
    ) -> List[FieldCandidate]:
        candidates: List[FieldCandidate] = []

        for raw_line in lines:
            line = self.clean_line(raw_line)

            if not line:
                continue

            match = self.FIELD_NAME_PATTERN.match(line)

            if not match:
                continue

            level_text = match.group("level")
            name = match.group("name").upper()
            rest = match.group("rest").strip()

            if level_text == "88":
                continue

            if name.startswith("FILLER"):
                continue

            candidates.append(
                FieldCandidate(
                    level=int(level_text),
                    name=name,
                    rest=rest,
                    original_line=line,
                )
            )

        return candidates

    def _mark_and_filter_leaf_fields(
        self,
        candidates: List[FieldCandidate],
    ) -> List[FieldCandidate]:
        """
        Marks parent/group fields and returns only leaf fields.

        COBOL group rule:
        A field is a group field if a following field has a greater level
        before the structure returns to the same or lower level.

        Example:

            02 OFFICE-ZIP-0450
            04 OFFICE-ZIP-FIRST-FIVE-0450
            04 OFFICE-ZIP-LAST-FOUR-0450

        OFFICE-ZIP-0450 is a group field and is skipped.
        The two level-04 fields are retained.
        """

        for index, candidate in enumerate(candidates):
            for next_candidate in candidates[index + 1 :]:
                if next_candidate.level <= candidate.level:
                    break

                if next_candidate.level > candidate.level:
                    candidate.has_child = True
                    break

        return [
            candidate
            for candidate in candidates
            if not candidate.has_child
        ]

    def clean_line(
        self,
        line: str,
    ) -> str:
        if line is None:
            return ""

        cleaned = line.strip()

        cleaned = cleaned.replace("\u00a0", " ")
        cleaned = re.sub(r"\s+", " ", cleaned)

        return cleaned