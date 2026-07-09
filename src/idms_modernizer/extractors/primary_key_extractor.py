import re

from idms_modernizer.services.name_normalizer import NameNormalizer


class PrimaryKeyExtractor:

    CALC_PATTERN = re.compile(
        r"CALC\s+USING\s+([A-Z0-9-]+)",
        re.IGNORECASE
    )

    def extract(
        self,
        lines: list[str]
    ) -> str | None:

        for line in lines:
            match = self.CALC_PATTERN.search(line)

            if match:
                return NameNormalizer.normalize(
                    match.group(1)
                )

        return None