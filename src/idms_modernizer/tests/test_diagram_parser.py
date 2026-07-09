from idms_modernizer.parsers.pdf_diagram_parser import (
    PdfDiagramParser
)


def test_diagram_parser():

    parser = (
        PdfDiagramParser()
    )

    relationships = (
        parser.parse(
            """
            DEPARTMENT
            EMPLOYEE
            """
        )
    )

    assert (
        len(relationships)
        == 1
    )

    assert (
        relationships[0].owner
        == "DEPARTMENT"
    )