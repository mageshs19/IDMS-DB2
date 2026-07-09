import re


class CobolZoneExtractor:
    """
    Extracts the IDMS region / zone from a schema record section.

    Examples:
        WITHIN INS-DEMO-REGION OFFSET 5 PGS FOR 20 PGS
        WITHIN
        EMP-DEMO-REGION OFFSET 5 PGS FOR 45 PGS

    Output:
        INS-DEMO-REGION
        EMP-DEMO-REGION
    """

    DIRECT_WITHIN_PATTERN = re.compile(
        r"\bWITHIN\s+([A-Z][A-Z0-9-]*REGION)\b",
        re.IGNORECASE,
    )

    REGION_PATTERN = re.compile(
        r"\b([A-Z][A-Z0-9-]*REGION)\b",
        re.IGNORECASE,
    )

    def extract(
        self,
        lines: list[str],
    ) -> str | None:
        cleaned_lines = [
            self.clean_line(line)
            for line in lines
            if line and self.clean_line(line)
        ]

        if not cleaned_lines:
            return None

        joined_text = " ".join(cleaned_lines)

        direct_match = self.DIRECT_WITHIN_PATTERN.search(
            joined_text,
        )

        if direct_match:
            return direct_match.group(1).upper()

        for index, line in enumerate(cleaned_lines):
            upper_line = line.upper()

            if upper_line == "WITHIN":
                region = self.find_region_after_within(
                    lines=cleaned_lines,
                    start_index=index + 1,
                )

                if region:
                    return region

            if "WITHIN" in upper_line:
                region = self.find_region_in_line(
                    line=line,
                )

                if region:
                    return region

                region = self.find_region_after_within(
                    lines=cleaned_lines,
                    start_index=index + 1,
                )

                if region:
                    return region

        return None

    def find_region_after_within(
        self,
        lines: list[str],
        start_index: int,
    ) -> str | None:
        for line in lines[start_index : start_index + 5]:
            region = self.find_region_in_line(
                line=line,
            )

            if region:
                return region

        return None

    def find_region_in_line(
        self,
        line: str,
    ) -> str | None:
        match = self.REGION_PATTERN.search(
            line,
        )

        if not match:
            return None

        return match.group(1).upper()

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