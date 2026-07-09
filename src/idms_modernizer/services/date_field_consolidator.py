import re

from idms_modernizer.domain.schema_models import DataField
from idms_modernizer.services.name_normalizer import NameNormalizer


class DateFieldConsolidator:
    """
    Consolidates legacy YEAR / MONTH / DAY field triplets into a DATE field.

    This implementation is generic.

    It does not hard-code business field prefixes such as:
    - START
    - BIRTH
    - CLAIM
    - EXPERTISE
    - STRUCTURE

    Instead, it detects any matching triplet:

        <BASE>_YEAR_<SUFFIX>
        <BASE>_MONTH_<SUFFIX>
        <BASE>_DAY_<SUFFIX>

    and produces:

        <BASE>_DATE_<SUFFIX>

    Example:

        START_YEAR_0415
        START_MONTH_0415
        START_DAY_0415

    becomes:

        START_DATE_0415

    Example:

        PATIENT_BIRTH_YEAR_0445
        PATIENT_BIRTH_MONTH_0445
        PATIENT_BIRTH_DAY_0445

    becomes:

        PATIENT_BIRTH_DATE_0445
    """

    YEAR_PATTERN = re.compile(
        r"^(?P<base>[A-Z0-9_]+)_YEAR_(?P<suffix>\d+)$",
        re.IGNORECASE,
    )

    @staticmethod
    def consolidate(
        fields: list[DataField],
    ) -> list[DataField]:
        result: list[DataField] = []
        consumed: set[str] = set()
        added_dates: set[str] = set()

        field_lookup = {
            NameNormalizer.normalize(field.name): field
            for field in fields
            if field and field.name
        }

        DateFieldConsolidator.add_existing_date_fields(
            fields=fields,
            result=result,
            added_dates=added_dates,
        )

        DateFieldConsolidator.add_consolidated_date_fields(
            field_lookup=field_lookup,
            result=result,
            consumed=consumed,
            added_dates=added_dates,
        )

        DateFieldConsolidator.add_remaining_fields(
            fields=fields,
            result=result,
            consumed=consumed,
            added_dates=added_dates,
        )

        return result

    @staticmethod
    def add_existing_date_fields(
        fields: list[DataField],
        result: list[DataField],
        added_dates: set[str],
    ) -> None:
        for field in fields:
            if not field or not field.name:
                continue

            normalized_name = NameNormalizer.normalize(
                field.name,
            )

            datatype = (
                field.datatype
                or ""
            ).upper()

            if datatype == "DATE":
                if normalized_name not in added_dates:
                    result.append(
                        field,
                    )

                    added_dates.add(
                        normalized_name,
                    )

    @staticmethod
    def add_consolidated_date_fields(
        field_lookup: dict[str, DataField],
        result: list[DataField],
        consumed: set[str],
        added_dates: set[str],
    ) -> None:
        for normalized_name in list(field_lookup.keys()):
            match = DateFieldConsolidator.YEAR_PATTERN.match(
                normalized_name,
            )

            if not match:
                continue

            base = match.group(
                "base",
            )

            suffix = match.group(
                "suffix",
            )

            year_name = f"{base}_YEAR_{suffix}"
            month_name = f"{base}_MONTH_{suffix}"
            day_name = f"{base}_DAY_{suffix}"
            date_name = f"{base}_DATE_{suffix}"

            if not DateFieldConsolidator.has_complete_date_triplet(
                field_lookup=field_lookup,
                year_name=year_name,
                month_name=month_name,
                day_name=day_name,
            ):
                continue

            if date_name not in added_dates:
                result.append(
                    DataField(
                        name=date_name,
                        datatype="DATE",
                        length=None,
                        scale=None,
                        picture=None,
                    )
                )

                added_dates.add(
                    date_name,
                )

            consumed.add(
                year_name,
            )

            consumed.add(
                month_name,
            )

            consumed.add(
                day_name,
            )

    @staticmethod
    def has_complete_date_triplet(
        field_lookup: dict[str, DataField],
        year_name: str,
        month_name: str,
        day_name: str,
    ) -> bool:
        return (
            year_name in field_lookup
            and month_name in field_lookup
            and day_name in field_lookup
        )

    @staticmethod
    def add_remaining_fields(
        fields: list[DataField],
        result: list[DataField],
        consumed: set[str],
        added_dates: set[str],
    ) -> None:
        for field in fields:
            if not field or not field.name:
                continue

            normalized_name = NameNormalizer.normalize(
                field.name,
            )

            if normalized_name in consumed:
                continue

            if normalized_name in added_dates:
                continue

            result.append(
                field,
            )