import re

from idms_modernizer.domain.schema_models import DataField
from idms_modernizer.services.name_normalizer import NameNormalizer


class DateFieldConsolidator:
    """
    Consolidates legacy date child fields into one DATE field.

    Supports:
    - YEAR / MONTH / DAY
    - YR / MO / DY
    - Y / M / D
    - YY / MM / DD
    - YYYY / MM / DD
    - DY / DM / DD
    """

    YEAR_PARTS = {
        "YEAR",
        "YR",
        "Y",
        "YY",
        "YYYY",
        "DY",
    }

    MONTH_PARTS = {
        "MONTH",
        "MON",
        "MO",
        "M",
        "MM",
        "DM",
    }

    DAY_PARTS = {
        "DAY",
        "D",
        "DD",
    }

    @staticmethod
    def consolidate(
        fields: list[DataField],
    ) -> list[DataField]:
        result: list[DataField] = []
        consumed: set[str] = set()
        added_dates: set[str] = set()

        date_groups = DateFieldConsolidator.collect_date_groups(
            fields=fields,
        )

        for date_name, parts in date_groups.items():
            if not DateFieldConsolidator.has_complete_date_group(
                parts=parts,
            ):
                continue

            normalized_date_name = NameNormalizer.normalize(
                date_name,
            )

            if normalized_date_name in added_dates:
                continue

            template = (
                parts.get("YEAR")
                or parts.get("MONTH")
                or parts.get("DAY")
            )

            result.append(
                DataField(
                    name=date_name,
                    level=DateFieldConsolidator.parent_level(
                        field=template,
                    ),
                    datatype="DATE",
                    length=None,
                    scale=None,
                    picture=None,
                    start_position=DateFieldConsolidator.min_start_position(
                        parts=parts,
                    ),
                    end_position=DateFieldConsolidator.max_end_position(
                        parts=parts,
                    ),
                    basetype="DATE",
                    has_child=True,
                    is_group=True,
                )
            )

            added_dates.add(
                normalized_date_name,
            )

            for part_field in parts.values():
                consumed.add(
                    NameNormalizer.normalize(
                        part_field.name,
                    )
                )

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

        return result

    @staticmethod
    def collect_date_groups(
        fields: list[DataField],
    ) -> dict[str, dict[str, DataField]]:
        groups: dict[str, dict[str, DataField]] = {}

        for field in fields:
            parsed = DateFieldConsolidator.parse_date_part(
                field_name=field.name,
            )

            if parsed is None:
                continue

            date_name = parsed["date_name"]
            part = parsed["part"]

            if date_name not in groups:
                groups[date_name] = {}

            groups[date_name][part] = field

        return groups

    @staticmethod
    def parse_date_part(
        field_name: str,
    ) -> dict[str, str] | None:
        tokens = DateFieldConsolidator.split_tokens(
            value=field_name,
        )

        if len(tokens) < 2:
            return None

        for index, token in enumerate(tokens):
            part = DateFieldConsolidator.date_part_type(
                token=token,
                tokens=tokens,
            )

            if part is None:
                continue

            date_tokens = tokens.copy()
            date_tokens[index] = "DATE"

            return {
                "date_name": " ".join(date_tokens),
                "part": part,
            }

        return None

    @staticmethod
    def date_part_type(
        token: str,
        tokens: list[str],
    ) -> str | None:
        token = token.upper()

        has_dy_dm_dd = (
            "DY" in tokens
            and "DM" in tokens
            and "DD" in tokens
        )

        if token in DateFieldConsolidator.YEAR_PARTS:
            if token == "DY" and not has_dy_dm_dd:
                return "DAY"

            return "YEAR"

        if token in DateFieldConsolidator.MONTH_PARTS:
            return "MONTH"

        if token in DateFieldConsolidator.DAY_PARTS:
            return "DAY"

        return None

    @staticmethod
    def has_complete_date_group(
        parts: dict[str, DataField],
    ) -> bool:
        return (
            "YEAR" in parts
            and "MONTH" in parts
            and "DAY" in parts
        )

    @staticmethod
    def parent_level(
        field: DataField | None,
    ) -> int | None:
        if field is None:
            return None

        level = getattr(
            field,
            "level",
            None,
        )

        if level is None:
            return None

        try:
            return max(
                int(level) - 1,
                1,
            )

        except Exception:
            return level

    @staticmethod
    def min_start_position(
        parts: dict[str, DataField],
    ) -> int | None:
        values: list[int] = []

        for field in parts.values():
            value = getattr(
                field,
                "start_position",
                None,
            )

            if value is not None:
                values.append(
                    int(value),
                )

        if not values:
            return None

        return min(values)

    @staticmethod
    def max_end_position(
        parts: dict[str, DataField],
    ) -> int | None:
        values: list[int] = []

        for field in parts.values():
            value = getattr(
                field,
                "end_position",
                None,
            )

            if value is not None:
                values.append(
                    int(value),
                )

        if not values:
            return None

        return max(values)

    @staticmethod
    def split_tokens(
        value: str,
    ) -> list[str]:
        normalized = NameNormalizer.normalize(
            value,
        )

        return [
            token.upper()
            for token in re.split(
                r"[\s_-]+",
                normalized,
            )
            if token
        ]