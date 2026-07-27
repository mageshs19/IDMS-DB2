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
    Extracts IDMS schema fields.

    extract():
    - Existing safe behavior.
    - Returns only leaf fields for DDL / DB2 model / COBOL conversion.

    extract_all():
    - Excel mapping behavior.
    - Returns all fields including group/outer fields.
    """

    FIELD_NAME_PATTERN = re.compile(
        r"^\s*(?P<level>0[1-9]|[1-4][0-9]|88)\s+"
        r"(?P<name>[A-Z][A-Z0-9-]*|FILLER)\b"
        r"(?P<rest>.*)$",
        re.IGNORECASE,
    )

    OCCURS_PATTERN = re.compile(
        r"\bOCCURS\s+"
        r"(?P<min>[0-9]+)"
        r"(?:\s+TO\s+(?P<max>[0-9]+))?",
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

        return self.candidates_to_fields(
            candidates=leaf_candidates,
        )

    def extract_all(
        self,
        lines: List[str],
    ) -> List[DataField]:
        print("USING FIELD EXTRACTOR VERSION ALL-FIELDS-FOR-MAPPING")

        candidates = self.discover_candidates(
            lines=lines,
        )

        self.mark_group_fields(
            candidates=candidates,
        )

        return self.candidates_to_fields(
            candidates=candidates,
        )

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

    def mark_group_fields(
        self,
        candidates: List[FieldCandidate],
    ) -> None:
        for index, candidate in enumerate(candidates):
            candidate.has_child = False

            for next_candidate in candidates[index + 1 :]:
                if next_candidate.level <= candidate.level:
                    break

                candidate.has_child = True
                break

    def mark_and_filter_leaf_fields(
        self,
        candidates: List[FieldCandidate],
    ) -> List[FieldCandidate]:
        self.mark_group_fields(
            candidates=candidates,
        )

        return [
            candidate
            for candidate in candidates
            if not candidate.has_child
        ]

    def candidates_to_fields(
        self,
        candidates: List[FieldCandidate],
    ) -> List[DataField]:
        fields: List[DataField] = []
        seen: Set[str] = set()

        for candidate in candidates:
            name = candidate.name.upper()

            if name in seen:
                continue

            seen.add(
                name,
            )

            occurs_min, occurs_max = self.extract_occurs(
                text=candidate.rest,
            )

            fields.append(
                DataField(
                    name=name,
                    level=candidate.level,
                    has_child=candidate.has_child,
                    is_group=candidate.has_child,
                    occurs=occurs_max is not None,
                    occurs_min=occurs_min,
                    occurs_max=occurs_max,
                    raw_line=candidate.original_line,
                    rest=candidate.rest,
                )
            )

        return fields

    def extract_occurs(
        self,
        text: str,
    ) -> tuple[int | None, int | None]:
        if not text:
            return None, None

        match = self.OCCURS_PATTERN.search(
            text,
        )

        if not match:
            return None, None

        occurs_min = int(
            match.group("min"),
        )

        occurs_max = (
            int(match.group("max"))
            if match.group("max")
            else occurs_min
        )

        return occurs_min, occurs_max

    def clean_line(
        self,
        line: str,
    ) -> str:
        if not line:
            return ""

        cleaned = str(line).strip()
        cleaned = cleaned.replace("\u00a0", " ")
        cleaned = re.sub(r"\s+", " ", cleaned)

        return cleaned.strip()