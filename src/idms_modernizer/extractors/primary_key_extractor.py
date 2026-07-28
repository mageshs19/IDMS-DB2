import re

from idms_modernizer.services.name_normalizer import NameNormalizer


class PrimaryKeyExtractor:
    """
    Extracts IDMS CALC primary key metadata.

    Generic behavior only:
    - No hardcoded record names.
    - No hardcoded key names.
    - Handles listing formats with dots, spaces, and split lines.

    Supported examples:
    - LOCATION MODE CALC USING EMP-ID-0415
    - LOCATION MODE........ CALC USING KY-VMBFC DUPLICATES NOT ALLOWED
    - CALC USING KY-VMBFC
    - SET CONTROL ITEM FOR CALC <start> <length>
    """

    CALC_PATTERN = re.compile(
        r"\bCALC\s+USING\s+([A-Z0-9-]+)\b",
        re.IGNORECASE,
    )

    CONTROL_ITEM_PATTERN = re.compile(
        r"\bSET\s+CONTROL\s+ITEM\s+FOR\s+CALC"
        r"(?:\s+(?P<start>[0-9]+)\s+(?P<length>[0-9]+))?",
        re.IGNORECASE,
    )

    CONTROL_ITEM_FOLLOWING_CALC_PATTERN = re.compile(
        r"\bCALC\s+(?P<start>[0-9]+)\s+(?P<length>[0-9]+)\b",
        re.IGNORECASE,
    )

    def extract(
        self,
        lines: list[str],
    ) -> str | None:
        cleaned_lines = [
            self.clean_line(line=line)
            for line in lines or []
        ]

        joined_text = " ".join(
            line
            for line in cleaned_lines
            if line
        )

        match = self.CALC_PATTERN.search(joined_text)

        if match:
            return NameNormalizer.normalize(
                match.group(1),
            )

        for line in cleaned_lines:
            match = self.CALC_PATTERN.search(line)

            if match:
                return NameNormalizer.normalize(
                    match.group(1),
                )

        return None

    def extract_control_item(
        self,
        lines: list[str],
    ) -> dict[str, int] | None:
        cleaned_lines = [
            self.clean_line(line=line)
            for line in lines or []
            if self.clean_line(line=line)
        ]

        joined_text = " ".join(cleaned_lines)

        match = self.CONTROL_ITEM_PATTERN.search(joined_text)

        if match:
            start = match.group("start")
            length = match.group("length")

            if start and length:
                return {
                    "start": int(start),
                    "length": int(length),
                }

        match = self.CONTROL_ITEM_FOLLOWING_CALC_PATTERN.search(joined_text)

        if match:
            return {
                "start": int(match.group("start")),
                "length": int(match.group("length")),
            }

        return None

    def clean_line(
        self,
        line: str,
    ) -> str:
        value = str(line or "").upper()

        value = value.replace(".", " ")
        value = value.replace("=", " ")
        value = value.replace(":", " ")
        value = value.replace("\u00a0", " ")

        value = re.sub(
            r"\s+",
            " ",
            value,
        )

        return value.strip()