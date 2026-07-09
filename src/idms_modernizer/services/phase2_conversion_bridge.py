class Phase2ConversionBridge:
    """
    Bridge from Phase 1 outputs to the Phase 2 converter.

    Import is intentionally lazy so Phase 1 UI can still load even if
    Phase 2 package has a missing or broken module.
    """

    def convert(
        self,
        cobol_text: str,
        canonical_json: str,
        phase2_metadata_json: str,
        ddl_text: str,
        idms_schema_text: str | None = None,
        relationship_overrides_json: str | None = None,
        target_program: str | None = None,
        use_ddl: bool = True,
        use_idms_schema: bool = False,
        use_overrides: bool = False
    ) -> tuple[str, list[str]]:

        if not cobol_text or not cobol_text.strip():
            raise ValueError(
                "COBOL code is required for Phase 2 conversion."
            )

        try:
            from idms_db2_converter.services.conversion_service import (
                ConversionService
            )

        except Exception as exc:
            raise RuntimeError(
                "Phase 2 converter package could not be loaded. "
                "Check src/idms_db2_converter files. "
                f"Details: {exc}"
            ) from exc

        if not canonical_json or not canonical_json.strip():
            canonical_json = '{"records": [], "sets": [], "relationships": []}'

        if not phase2_metadata_json:
            phase2_metadata_json = ""

        if not ddl_text:
            ddl_text = ""

        if not idms_schema_text:
            idms_schema_text = ""

        if not relationship_overrides_json:
            relationship_overrides_json = ""

        service = ConversionService()

        converted, validation_messages = service.convert_retrieval(
            cobol_text=cobol_text,
            canonical_json=canonical_json,
            phase2_metadata_json=phase2_metadata_json,
            ddl_text=ddl_text if use_ddl else None,
            idms_schema_text=(
                idms_schema_text
                if use_idms_schema
                else None
            ),
            relationship_overrides_json=(
                relationship_overrides_json
                if use_overrides and relationship_overrides_json.strip()
                else None
            ),
            target_program=(
                target_program.strip()
                if target_program and target_program.strip()
                else None
            )
        )

        return converted, validation_messages