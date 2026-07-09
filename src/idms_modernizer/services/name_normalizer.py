import re


class NameNormalizer:

    @staticmethod
    def normalize(
        name: str | None
    ) -> str:

        if not name:
            return ""

        normalized = name.strip().upper()
        normalized = normalized.replace("-", "_")
        normalized = re.sub(
            r"[^A-Z0-9_]",
            "_",
            normalized
        )
        normalized = re.sub(
            r"_+",
            "_",
            normalized
        )

        return normalized.strip("_")