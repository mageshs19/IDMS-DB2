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

    Behavior:
    - Identifies COBOL level numbers.
    - Preserves the level number in DataField.level.
    - Skips FILLER.
    - Skips level 88 condition names.
    - Skips group / outer fields that have subordinate children.
    - Returns only leaf / inner fields.

    Example:
        02 EMP-NAME-0415
        03 EMP-FIRST-NAME-0415 DISPLAY X(10) 1 10
        03 EMP-LAST-NAME-0415 DISPLAY X(15) 11 15

    Result:
        03 EMP-FIRST-NAME-0415
        03 EMP-LAST-NAME-0415

    Skipped:
        02 EMP-NAME-0415
    """

    FIELD_NAME_PATTERN = re.compile(
        r"^\s*(?P<level>0[1-9]|[1-4][0-9]|88)\s+"
        r"(?P<name>[A-Z][A-Z0-9-]*|FILLER)\b"
        r"(?P<rest>.*)$",
        re.IGNORECASE,
    )

    def extract(
        self,
        lines: List[str],
    ) -> List[DataField]:
        print("USING FIELD EXTRACTOR VERSION LEAF-ONLY-WITH-LEVEL")

        candidates = self.discover_candidates(
            lines=lines,
        )

        leaf_candidates = self.mark_and_filter_leaf_fields(
            candidates=candidates,
        )

        fields: List[DataField] = []
        seen: Set[str] = set()

        for candidate in leaf_candidates:
            name = candidate.name.upper()

            if name in seen:
                continue

            seen.add(name)

            fields.append(
                DataField(
                    name=name,
                    level=candidate.level,
                )
            )

        return fields

    def discover_candidates(
        self,
        lines: List[str],
    ) -> List[FieldCandidate]:
        candidates: List[FieldCandidate] = []

        for line in lines:
            cleaned_line = self.clean_line(
                line=line,
            )

            if not cleaned_line:
                continue

            match = self.FIELD_NAME_PATTERN.match(
                cleaned_line,
            )

            if not match:
                continue

            level = int(
                match.group("level"),
            )

            name = match.group("name").upper()
            rest = match.group("rest").strip()

            if name == "FILLER":
                continue

            if level == 88:
                continue

            candidates.append(
                FieldCandidate(
                    level=level,
                    name=name,
                    rest=rest,
                    original_line=cleaned_line,
                )
            )

        return candidates

    def mark_and_filter_leaf_fields(
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
            for next_candidate in candidates[index + 1:]:
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
        line: str | None,
    ) -> str:
        if line is None:
            return ""

        cleaned = str(line).strip()

        cleaned = cleaned.replace(
            "\t",
            " ",
        )

        cleaned = cleaned.replace(
            "\u00a0",
            " ",
        )

        cleaned = re.sub(
            r"<[^>]+>",
            " ",
            cleaned,
        )

        cleaned = re.sub(
            r"\s+",
            " ",
            cleaned,
        ).strip()

        return cleaned