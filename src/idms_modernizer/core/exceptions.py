class ModernizerException(
    Exception
):
    pass


class PdfExtractionException(
    ModernizerException
):
    pass


class SchemaParsingException(
    ModernizerException
):
    pass


class ValidationException(
    ModernizerException
):
    pass