from pathlib import Path
from tempfile import NamedTemporaryFile

import streamlit as st

from idms_modernizer.core.config import settings
from idms_modernizer.core.utils import ensure_directory

from idms_modernizer.services.metadata_service import MetadataService
from idms_modernizer.services.canonical_schema_builder import (
    CanonicalSchemaBuilder,
)
from idms_modernizer.services.canonical_reconciler import (
    CanonicalReconciler,
)
from idms_modernizer.services.db2_model_builder import DB2ModelBuilder
from idms_modernizer.generators.ddl_generator import DDLGenerator
from idms_modernizer.services.excel_sheet_mapping_service import (
    ExcelSheetMappingService,
)


def initialize_directories() -> None:
    ensure_directory(settings.input_dir)
    ensure_directory(settings.output_dir)


def initialize_session_state() -> None:
    defaults = {
        "schema_only_generated": False,
        "schema_only_metadata": None,
        "schema_only_canonical_schema": None,
        "schema_only_db2_model": None,
        "schema_only_ddl_text": "",
        "schema_only_excel_mapping_rows": [],
        "schema_only_error": "",
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def save_uploaded_pdf(uploaded_file) -> str:
    suffix = Path(uploaded_file.name).suffix or ".pdf"

    with NamedTemporaryFile(
        delete=False,
        suffix=suffix,
    ) as temp_file:
        temp_file.write(
            uploaded_file.getbuffer(),
        )
        return temp_file.name


def generate_schema_only_outputs(schema_pdf) -> None:
    st.session_state.schema_only_error = ""

    try:
        schema_path = save_uploaded_pdf(
            schema_pdf,
        )

        metadata_service = MetadataService()

        metadata = metadata_service.build_metadata(
            schema_path,
        )

        canonical_builder = CanonicalSchemaBuilder()

        canonical_schema = canonical_builder.build(
            metadata,
        )

        reconciler = CanonicalReconciler()

        canonical_schema = reconciler.reconcile(
            canonical_schema=canonical_schema,
            metadata=metadata,
        )

        db2_builder = DB2ModelBuilder()

        db2_model = db2_builder.build(
            canonical_schema,
        )

        ddl_generator = DDLGenerator()

        ddl_text = ddl_generator.generate(
            db2_model,
        )

        excel_mapping_service = ExcelSheetMappingService()

        excel_mapping_rows = excel_mapping_service.build(
            metadata=metadata,
            db2_model=db2_model,
        )

        st.session_state.schema_only_metadata = metadata
        st.session_state.schema_only_canonical_schema = canonical_schema
        st.session_state.schema_only_db2_model = db2_model
        st.session_state.schema_only_ddl_text = ddl_text
        st.session_state.schema_only_excel_mapping_rows = excel_mapping_rows
        st.session_state.schema_only_generated = True

    except Exception as exc:
        st.session_state.schema_only_generated = False
        st.session_state.schema_only_error = str(exc)


def render_main_tab() -> None:
    st.markdown("## Schema Listing Only")

    st.info(
        "Upload only the Schema Listing PDF to generate Metadata Overview, "
        "DB2 DDL, and Excel Sheet Mapping."
    )

    schema_pdf = st.file_uploader(
        "Schema Listing PDF",
        type=["pdf"],
        key="schema_only_schema_listing_pdf",
    )

    generate_clicked = st.button(
        "Generate Schema Outputs",
        type="primary",
        use_container_width=True,
    )

    if generate_clicked:
        if schema_pdf is None:
            st.error("Please upload a Schema Listing PDF.")
            return

        generate_schema_only_outputs(
            schema_pdf,
        )

    if st.session_state.schema_only_error:
        st.error(
            st.session_state.schema_only_error,
        )

    if st.session_state.schema_only_generated:
        metadata = st.session_state.schema_only_metadata
        db2_model = st.session_state.schema_only_db2_model

        st.success("Schema-only outputs generated successfully.")

        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric(
                "Records",
                len(metadata.records),
            )

        with col2:
            st.metric(
                "Relationships",
                len(metadata.relationships),
            )

        with col3:
            st.metric(
                "DB2 Tables",
                len(db2_model.tables),
            )


def render_metadata_overview_tab() -> None:
    if not st.session_state.schema_only_generated:
        st.info("Generate outputs from the Main tab first.")
        return

    metadata = st.session_state.schema_only_metadata

    st.markdown("## Metadata Overview")

    record_rows = []

    for record in metadata.records:
        record_rows.append(
            {
                "Record": record.name,
                "Cobol Zone": record.cobol_zone or "",
                "Primary Key": record.primary_key or "",
                "Field Count": len(record.fields),
                "Set Membership Count": len(record.set_memberships),
            }
        )

    st.markdown("### Records")

    st.dataframe(
        record_rows,
        use_container_width=True,
        hide_index=True,
    )

    relationship_rows = []

    for relationship in metadata.relationships:
        relationship_rows.append(
            {
                "Owner Record": relationship.owner_record,
                "Member Record": relationship.member_record,
                "Set Name": relationship.set_name,
                "Cardinality": relationship.cardinality,
            }
        )

    st.markdown("### Relationships")

    if relationship_rows:
        st.dataframe(
            relationship_rows,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No relationships detected.")


def render_ddl_tab() -> None:
    if not st.session_state.schema_only_generated:
        st.info("Generate outputs from the Main tab first.")
        return

    st.markdown("## DB2 DDL")

    st.code(
        st.session_state.schema_only_ddl_text,
        language="sql",
    )


def render_excel_sheet_mapping_tab() -> None:
    if not st.session_state.schema_only_generated:
        st.info("Generate outputs from the Main tab first.")
        return

    st.markdown("## Excel Sheet Mapping")

    rows = st.session_state.schema_only_excel_mapping_rows

    if not rows:
        st.info("No mapping rows generated.")
        return

    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
    )


def main() -> None:
    initialize_directories()
    initialize_session_state()

    st.set_page_config(
        page_title="Schema Listing Mapping",
        layout="wide",
    )

    st.title("Schema Listing Mapping")

    st.caption(
        "Upload Schema Listing PDF only and generate DB2 DDL plus "
        "Excel-style mapping."
    )

    tabs = st.tabs(
        [
            "Main",
            "Metadata Overview",
            "DB2 DDL",
            "Excel Sheet Mapping",
        ]
    )

    with tabs[0]:
        render_main_tab()

    with tabs[1]:
        render_metadata_overview_tab()

    with tabs[2]:
        render_ddl_tab()

    with tabs[3]:
        render_excel_sheet_mapping_tab()


if __name__ == "__main__":
    main()