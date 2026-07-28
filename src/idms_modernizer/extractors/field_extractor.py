import re

from dataclasses import dataclass
from typing import List

from idms_modernizer.domain.schema_models import DataField


@dataclass
class FieldCandidate:
    level: int
    name: str
    rest: str
    original_line: str
    has_child: bool = False
    is_group: bool = False
    occurs: bool = False
    occurs_min: int | None = None
    occurs_max: int | None = None


class FieldExtractor:
    """
    Extracts IDMS schema fields.

    Generic behavior only:
    - No business field names are hardcoded.
    - No record names are hardcoded.
    - Physical extraction and Sheet Mapping extraction are separated.

    extract():
    - Used for physical / DDL-safe fields.
    - Returns only leaf fields.
    - Excludes FILLER by default because FILLER should not become a DB2 column.

    extract_all():
    - Used for Excel Sheet Mapping.
    - Returns all fields:
      groups, subgroups, leaves, date groups, date parts, OCCURS groups, and FILLER.
    - Includes FILLER by default so Sheet Mapping can show FILLER rows.
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

    def __init__(
        self,
        include_filler: bool = False,
        auto_number_filler: bool = False,
    ) -> None:
        self.include_filler = include_filler
        self.auto_number_filler = auto_number_filler

    def extract(
        self,
        lines: List[str],
    ) -> List[DataField]:
        """
        Physical / DDL-safe extraction.

        FILLER is excluded here because physical DB2 columns should not be created
        from COBOL FILLER.
        """

        print("USING FIELD EXTRACTOR VERSION LEAF-ONLY-WITH-LEVEL")

        candidates = self.discover_candidates(
            lines=lines,
            include_filler=False,
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
        include_filler: bool = True,
    ) -> List[DataField]:
        """
        Excel Sheet Mapping extraction.

        FILLER is included here so Sheet Mapping can show FILLER rows.
        """

        print("USING FIELD EXTRACTOR VERSION ALL-FIELDS-FOR-MAPPING")

        candidates = self.discover_candidates(
            lines=lines,
            include_filler=include_filler,
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
        include_filler: bool | None = None,
    ) -> List[FieldCandidate]:
        candidates: List[FieldCandidate] = []

        if include_filler is None:
            include_filler = self.include_filler

        filler_index = 0

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

            if level == 88:
                continue

            if name == "FILLER":
                if not include_filler:
                    continue

                filler_index += 1

                candidate_name = name

                if self.auto_number_filler:
                    candidate_name = f"FILLER_{filler_index}"
            else:
                candidate_name = name

            occurs_info = self.parse_occurs(
                text=rest,
            )

            candidate = FieldCandidate(
                level=level,
                name=candidate_name,
                rest=rest,
                original_line=cleaned_line,
                occurs=occurs_info["occurs"],
                occurs_min=occurs_info["occurs_min"],
                occurs_max=occurs_info["occurs_max"],
            )

            candidates.append(candidate)

        return candidates

    def mark_group_fields(
        self,
        candidates: List[FieldCandidate],
    ) -> None:
        for index, candidate in enumerate(candidates):
            candidate.has_child = False
            candidate.is_group = False

            for later_candidate in candidates[index + 1:]:
                if later_candidate.level <= candidate.level:
                    break

                if later_candidate.level > candidate.level:
                    candidate.has_child = True
                    candidate.is_group = True
                    break

    def mark_and_filter_leaf_fields(
        self,
        candidates: List[FieldCandidate],
    ) -> List[FieldCandidate]:
        self.mark_group_fields(
            candidates=candidates,
        )

        leaf_candidates: List[FieldCandidate] = []

        for candidate in candidates:
            if candidate.has_child:
                continue

            leaf_candidates.append(candidate)

        return leaf_candidates

    def candidates_to_fields(
        self,
        candidates: List[FieldCandidate],
    ) -> List[DataField]:
        fields: List[DataField] = []

        for candidate in candidates:
            display_name = candidate.name

            if display_name.startswith("FILLER_"):
                display_name = "FILLER"

            field = DataField(
                name=display_name,
                level=candidate.level,
                rest=candidate.rest,
                raw_line=candidate.original_line,
                has_child=candidate.has_child,
                is_group=candidate.is_group,
                occurs=candidate.occurs,
                occurs_min=candidate.occurs_min,
                occurs_max=candidate.occurs_max,
            )

            fields.append(field)

        return fields

    def parse_occurs(
        self,
        text: str,
    ) -> dict:
        match = self.OCCURS_PATTERN.search(
            text or "",
        )

        if not match:
            return {
                "occurs": False,
                "occurs_min": None,
                "occurs_max": None,
            }

        occurs_min = self.safe_int(
            value=match.group("min"),
        )

        occurs_max_raw = match.group("max")

        occurs_max = (
            self.safe_int(
                value=occurs_max_raw,
            )
            if occurs_max_raw is not None
            else occurs_min
        )

        return {
            "occurs": True,
            "occurs_min": occurs_min,
            "occurs_max": occurs_max,
        }

    def clean_line(
        self,
        line: str,
    ) -> str:
        value = str(line or "").strip()

        if not value:
            return ""

        value = value.replace("\u00a0", " ")
        value = re.sub(r"\s+", " ", value)

        return value.strip()

    def safe_int(
        self,
        value,
    ) -> int | None:
        try:
            if value is None:
                return None

            return int(value)
        except Exception:
            return None