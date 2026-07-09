from idms_modernizer.domain.schema_models import DataField
from idms_modernizer.services.name_normalizer import NameNormalizer
from idms_modernizer.services.date_field_consolidator import DateFieldConsolidator
from idms_modernizer.services.db2_mapping_service import DB2MappingService


def test_name_normalizer_removes_suffix_and_normalizes():
    assert (
        NameNormalizer.normalize(
            "CLAIM-YEAR-0405"
        )
        == "CLAIM_YEAR"
    )
    assert (
        NameNormalizer.normalize(
            "EMP-ID 0415"
        )
        == "EMP_ID"
    )
    assert (
        NameNormalizer.normalize(
            "  CLAIM--MONTH-0405  "
        )
        == "CLAIM_MONTH"
    )


def test_date_field_consolidator_consolidates_suffixed_date_fields():
    fields = [
        DataField(name="CLAIM-YEAR-0405"),
        DataField(name="CLAIM-MONTH-0405"),
        DataField(name="CLAIM-DAY-0405"),
        DataField(name="OTHER-FIELD-0405"),
    ]

    consolidated = DateFieldConsolidator.consolidate(
        fields
    )

    assert any(
        field.name == "CLAIM_DATE"
        and field.datatype == "DATE"
        for field in consolidated
    )
    assert any(
        field.name == "OTHER-FIELD-0405"
        and field.datatype is None
        for field in consolidated
    )
    assert len(consolidated) == 2


def test_db2_mapping_service_preserves_date_and_varchar_length():
    mapper = DB2MappingService()

    date_column = DataField(
        name="CLAIM_DATE",
        datatype="DATE"
    )
    assert mapper.map_datatype(date_column) == "DATE"

    timestamp_column = DataField(
        name="EVENT_TS",
        datatype="TIMESTAMP"
    )
    assert mapper.map_datatype(timestamp_column) == "TIMESTAMP"

    string_column = DataField(
        name="NAME",
        datatype="DISPLAY",
        length=40,
    )
    assert mapper.map_datatype(string_column) == "VARCHAR(40)"
