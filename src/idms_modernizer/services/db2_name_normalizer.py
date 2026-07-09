from idms_modernizer.services.name_normalizer import NameNormalizer


class DB2NameNormalizer:

    REMOVE_RECORD_SUFFIX = False

    @staticmethod
    def normalize_record_name(
        name: str | None
    ) -> str:

        return NameNormalizer.normalize(name)

    @staticmethod
    def normalize_column_name(
        name: str | None
    ) -> str:

        normalized = NameNormalizer.normalize(name)

        if not DB2NameNormalizer.REMOVE_RECORD_SUFFIX:
            return normalized

        parts = normalized.split("_")

        if (
            len(parts) > 1
            and parts[-1].isdigit()
            and len(parts[-1]) == 4
        ):
            return "_".join(parts[:-1])

        return normalized