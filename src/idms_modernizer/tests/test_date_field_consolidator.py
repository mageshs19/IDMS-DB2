from idms_modernizer.services.date_field_consolidator import (
    DateFieldConsolidator
)

from idms_modernizer.domain.schema_models import (
    DataField
)


def test_consolidate_year_month_day():
    fields = [
        DataField(name="START_YEAR"),
        DataField(name="START_MONTH"),
        DataField(name="START_DAY")
    ]

    out = DateFieldConsolidator.consolidate(fields)

    assert len(out) == 1
    assert out[0].name == "START_DATE"
    assert out[0].datatype == "DATE"


def test_consolidate_variants():
    fields = [
        DataField(name="FINISH_YR"),
        DataField(name="FINISH_MO"),
        DataField(name="FINISH_DY")
    ]

    out = DateFieldConsolidator.consolidate(fields)

    assert len(out) == 1
    assert out[0].name == "FINISH_DATE"
    assert out[0].datatype == "DATE"


def test_preserve_existing_full_date():
    fields = [
        DataField(name="BIRTH_DATE", datatype="DATE"),
        DataField(name="BIRTH_YEAR"),
        DataField(name="BIRTH_MONTH")
    ]

    out = DateFieldConsolidator.consolidate(fields)

    # Should keep the existing BIRTH_DATE and not create duplicate
    names = [f.name for f in out]
    assert "BIRTH_DATE" in names
    assert all(n.startswith("BIRTH_") for n in names)


def test_keep_year_only():
    fields = [
        DataField(name="CLAIM_YEAR")
    ]

    out = DateFieldConsolidator.consolidate(fields)

    assert len(out) == 1
    assert out[0].name == "CLAIM_YEAR"
