import re

from idms_modernizer.services.name_normalizer import NameNormalizer


class PrimaryKeyExtractor:
    """
    Extracts IDMS CALC primary key metadata.

    Supports:
    - LOCATION MODE CALC USING <field>
    - SET CONTROL ITEM FOR CALC <start> <length> ...

    The SET CONTROL ITEM line is important for group CALC keys such as
    KY-FFRECAB, where the group may not have its own PIC but has a defined
    CALC key start/length.
    """

    CALC_PATTERN = re.compile(
        r"CALC\s+USING\s+([A-Z0-9-]+)",
        re.IGNORECASE,
    )

    CONTROL_ITEM_PATTERN = re.compile(
        r"SET\s+CONTROL\s+ITEM\s+FOR\s+CALC(?:\s+(?P<start>[0-9]+)\s+(?P<length>[0-9]+))?",
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
        for line in lines:
            match = self.CALC_PATTERN.search(
                line,
            )

            if match:
                return NameNormalizer.normalize(
                    match.group(1),
                )

        return None

    def extract_control_item(
        self,
        lines: list[str],
    ) -> dict[str, int] | None:
        """
        Extracts CALC control item start/length.

        Handles both styles:

        SET CONTROL ITEM FOR CALC 3 26 ASC DUP FIRST

        and:

        SET CONTROL ITEM FOR
        CALC 3 26 ASC DUP FIRST
        """

        cleaned_lines = [
            self.clean_line(
                line=line,
            )
            for line in lines
            if self.clean_line(
                line=line,
            )
        ]

        for index, line in enumerate(
            cleaned_lines,
        ):
            if "SET CONTROL ITEM FOR" not in line.upper():
                continue

            window = " ".join(
                cleaned_lines[index : index + 5],
            )

            direct_match = self.CONTROL_ITEM_PATTERN.search(
                window,
            )

            if direct_match:
                start = direct_match.group(
                    "start",
                )
                length = direct_match.group(
                    "length",
                )

                if start and length:
                    return {
                        "start_position": int(start),
                        "length": int(length),
                        "end_position": int(start) + int(length) - 1,
                    }

            following_match = self.CONTROL_ITEM_FOLLOWING_CALC_PATTERN.search(
                window,
            )

            if following_match:
                start = int(
                    following_match.group("start"),
                )

                length = int(
                    following_match.group("length"),
                )

                return {
                    "start_position": start,
                    "length": length,
                    "end_position": start + length - 1,
                }

        return None

    def clean_line(
        self,
        line: str,
    ) -> str:
        if not line:
            return ""

        return " ".join(
            str(line).strip().split(),
        )