from idms_modernizer.parsers.pdf_schema_parser import (
    PdfSchemaParser
)


def test_schema_parser():

    sample_text = """

    RECORD NAME..... EMPLOYEE

    EMP-ID-0415

    EMP-FIRST-NAME-0415

    EMP-LAST-NAME-0415

    RECORD NAME..... DEPARTMENT

    DEPT-ID-0416

    DEPT-NAME-0416

    """

    parser = (
        PdfSchemaParser()
    )

    metadata = (
        parser.parse(
            sample_text
        )
    )

    assert (
        len(metadata.records)
        == 2
    )

    assert (
        metadata.records[0].name
        == "EMPLOYEE"
    )

    assert (
        len(
            metadata.records[0].fields
        )
        == 3
    )