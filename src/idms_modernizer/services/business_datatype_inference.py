class BusinessDatatypeInference:
    """
    Generic datatype inference.

    This class intentionally does not inspect field names.

    Reason:
    Field-name based rules such as PHONE, ZIP, SSN, CODE, ACCOUNT,
    POLICY, or LICENSE are business/domain assumptions and should not be
    hardcoded.

    Datatype should be decided upstream from:
    - IDMS PIC clause
    - USAGE
    - length
    - scale
    """

    @staticmethod
    def infer(
        field_name: str,
        current_type: str,
    ) -> str:
        if current_type:
            return current_type.upper()

        return "VARCHAR"