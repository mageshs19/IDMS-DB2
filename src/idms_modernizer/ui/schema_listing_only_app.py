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
    ensure_directory(
        settings.output_dir,
    )


def initialize_session_state() -> None:
    defaults = {
        "schema_only_generated": False,
        "schema_only_error": "",
        "schema_only_schema_path": "",
        "schema_only_metadata": None,
        "schema_only_canonical_schema": None,
        "schema_only_db2_model": None,
        "schema_only_ddl_text": "",
        "schema_only_excel_mapping_rows": [],
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_schema_only_outputs() -> None:
    st.session_state.schema_only_generated = False
    st.session_state.schema_only_error = ""
    st.session_state.schema_only_schema_path = ""
    st.session_state.schema_only_metadata = None
    st.session_state.schema_only_canonical_schema = None
    st.session_state.schema_only_db2_model = None
    st.session_state.schema_only_ddl_text = ""
    st.session_state.schema_only_excel_mapping_rows = []


def save_uploaded_schema_file(
    uploaded_file,
) -> str:
    suffix = Path(
        uploaded_file.name,
    ).suffix or ".pdf"

    with NamedTemporaryFile(
        delete=False,
        suffix=suffix,
    ) as temp_file:
        temp_file.write(
            uploaded_file.getbuffer(),
        )

        return temp_file.name


def generate_schema_outputs(
    schema_pdf,
) -> None:
    reset_schema_only_outputs()

    try:
        schema_path = save_uploaded_schema_file(
            uploaded_file=schema_pdf,
        )

        metadata_service = MetadataService()

        metadata = metadata_service.build_metadata(
            pdf_path=schema_path,
        )

        canonical_builder = CanonicalSchemaBuilder()

        canonical_schema = canonical_builder.build(
            metadata=metadata,
        )

        canonical_reconciler = CanonicalReconciler()

        canonical_schema = canonical_reconciler.reconcile(
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

        st.session_state.schema_only_schema_path = schema_path
        st.session_state.schema_only_metadata = metadata
        st.session_state.schema_only_canonical_schema = canonical_schema
        st.session_state.schema_only_db2_model = db2_model
        st.session_state.schema_only_ddl_text = ddl_text
        st.session_state.schema_only_excel_mapping_rows = excel_mapping_rows
        st.session_state.schema_only_generated = True

    except Exception as exc:
        st.session_state.schema_only_generated = False
        st.session_state.schema_only_error = str(
            exc,
        )


def build_mapping_row_count_by_table(
    rows: list[dict],
    include_total: bool = True,
) -> list[dict[str, int | str]]:
    """
    Builds table-level counts from the actual Excel Sheet Mapping rows.

    This count matches the detailed mapping table because it counts the
    generated mapping rows, not only DB2 physical columns.

    Output column order:
    - Column Field Count
    - Table Name
    """
    table_counts: dict[str, int] = {}

    for row in rows or []:
        table_name = (
            row.get("New DB2 Record")
            or row.get("Cobol Record IDMS")
            or ""
        )

        table_name = str(
            table_name,
        ).strip()

        if not table_name:
            continue

        table_counts[table_name] = table_counts.get(
            table_name,
            0,
        ) + 1

    output_rows: list[dict[str, int | str]] = []

    total_count = 0

    for table_name in sorted(table_counts):
        count = table_counts[table_name]

        output_rows.append(
            {
                "Column Field Count": count,
                "Table Name": table_name,
            }
        )

        total_count += count

    if include_total:
        output_rows.append(
            {
                "Column Field Count": total_count,
                "Table Name": "TOTAL",
            }
        )

    return output_rows


def build_db2_physical_column_count_rows(
    db2_model,
    include_total: bool = True,
) -> list[dict[str, int | str]]:
    """
    Builds table-level physical DB2 column counts.

    This is separate from the mapping row count because DATE child fields
    can create multiple mapping rows but only one DB2 physical DATE column.
    """
    table_rows: list[dict[str, int | str]] = []

    if db2_model is None:
        return table_rows

    total_count = 0

    for table in getattr(
        db2_model,
        "tables",
        [],
    ) or []:
        table_name = getattr(
            table,
            "name",
            "",
        )

        columns = getattr(
            table,
            "columns",
            [],
        ) or []

        count = len(
            columns,
        )

        table_rows.append(
            {
                "Column Field Count": count,
                "Table Name": table_name,
            }
        )

        total_count += count

    if include_total:
        table_rows.append(
            {
                "Column Field Count": total_count,
                "Table Name": "TOTAL",
            }
        )

    return table_rows


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
            st.error(
                "Please upload a Schema Listing PDF."
            )
            return

        with st.spinner(
            "Processing schema listing and generating outputs..."
        ):
            generate_schema_outputs(
                schema_pdf=schema_pdf,
            )

        if st.session_state.schema_only_generated:
            st.success(
                "Schema outputs generated successfully."
            )
        else:
            st.error(
                "Schema output generation failed."
            )

            if st.session_state.schema_only_error:
                st.error(
                    st.session_state.schema_only_error,
                )

    if st.session_state.schema_only_generated:
        st.markdown("### Output Status")

        metadata = st.session_state.schema_only_metadata
        db2_model = st.session_state.schema_only_db2_model
        mapping_rows = st.session_state.schema_only_excel_mapping_rows

        col1, col2, col3, col4 = st.columns(
            4,
        )

        with col1:
            st.metric(
                "Records",
                len(
                    metadata.records,
                )
                if metadata is not None
                else 0,
            )

        with col2:
            st.metric(
                "Relationships",
                len(
                    metadata.relationships,
                )
                if metadata is not None
                else 0,
            )

        with col3:
            st.metric(
                "DB2 Tables",
                len(
                    db2_model.tables,
                )
                if db2_model is not None
                else 0,
            )

        with col4:
            st.metric(
                "Sheet Mapping Rows",
                len(
                    mapping_rows,
                )
                if mapping_rows is not None
                else 0,
            )


def render_metadata_overview_tab() -> None:
    if not st.session_state.schema_only_generated:
        st.info(
            "Generate outputs from the Main tab first."
        )
        return

    metadata = st.session_state.schema_only_metadata
    db2_model = st.session_state.schema_only_db2_model
    mapping_rows = st.session_state.schema_only_excel_mapping_rows

    if metadata is None:
        st.info(
            "No metadata available."
        )
        return

    st.markdown("## Metadata Overview")

    st.markdown("### Records")

    record_rows = []

    for record in metadata.records:
        record_rows.append(
            {
                "Record": record.name,
                "Cobol Zone": record.cobol_zone or "",
                "Primary Key": record.primary_key or "",
                "Field Count": len(
                    record.fields,
                ),
                "Set Membership Count": len(
                    record.set_memberships,
                ),
            }
        )

    st.dataframe(
        record_rows,
        use_container_width=True,
        hide_index=True,
    )

    st.divider()

    st.markdown("### Table List and Mapping Row Counts")

    mapping_count_rows = build_mapping_row_count_by_table(
        rows=mapping_rows,
        include_total=True,
    )

    if mapping_count_rows:
        st.dataframe(
            mapping_count_rows,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(
            "No table mapping row counts available."
        )

    st.caption(
        "This count is based on the actual Excel Sheet Mapping rows, "
        "so the TOTAL matches the detailed mapping table."
    )

    st.divider()

    st.markdown("### DB2 Physical Column Counts")

    physical_column_count_rows = build_db2_physical_column_count_rows(
        db2_model=db2_model,
        include_total=True,
    )

    if physical_column_count_rows:
        st.dataframe(
            physical_column_count_rows,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(
            "No DB2 physical column counts available."
        )

    st.caption(
        "This count is based on DB2 physical columns. It can be lower than "
        "the mapping row count when COBOL YEAR, MONTH, and DAY fields map "
        "to one DB2 DATE column."
    )

    st.divider()

    st.markdown("### Records and Fields")

    record_names = [
        record.name
        for record in metadata.records
    ]

    if not record_names:
        st.info(
            "No records found."
        )
        return

    selected_record = st.selectbox(
        "Select a record",
        options=record_names,
    )

    selected_record_obj = None

    for record in metadata.records:
        if record.name == selected_record:
            selected_record_obj = record
            break

    if selected_record_obj is not None:
        st.write(
            f"Fields found: `{len(selected_record_obj.fields)}`"
        )

        field_rows = []

        for field in selected_record_obj.fields:
            field_rows.append(
                {
                    "Field": field.name,
                    "Level": field.level,
                    "Datatype": field.datatype,
                    "Length": field.length,
                    "Scale": field.scale,
                    "Picture": field.picture,
                    "Start Position": field.start_position,
                    "End Position": field.end_position,
                    "Basetype": field.basetype,
                }
            )

        st.dataframe(
            field_rows,
            use_container_width=True,
            hide_index=True,
        )

    with st.expander(
        "View all records and fields as JSON",
        expanded=False,
    ):
        st.json(
            [
                {
                    "record": record.name,
                    "cobol_zone": record.cobol_zone,
                    "primary_key": record.primary_key,
                    "fields": [
                        field.model_dump()
                        for field in record.fields
                    ],
                    "set_memberships": [
                        {
                            "set_name": getattr(
                                membership,
                                "set_name",
                                "",
                            ),
                            "relation_type": getattr(
                                membership,
                                "relation_type",
                                "",
                            ),
                            "owner_record": getattr(
                                membership,
                                "owner_record",
                                "",
                            ),
                            "member_record": getattr(
                                membership,
                                "member_record",
                                "",
                            ),
                        }
                        for membership in record.set_memberships
                    ],
                }
                for record in metadata.records
            ]
        )


def render_ddl_tab() -> None:
    if not st.session_state.schema_only_generated:
        st.info(
            "Generate outputs from the Main tab first."
        )
        return

    st.markdown("## DB2 DDL")

    ddl_text = st.session_state.schema_only_ddl_text

    if not ddl_text:
        st.info(
            "No DDL generated."
        )
        return

    st.code(
        ddl_text,
        language="sql",
    )


def render_excel_sheet_mapping_tab() -> None:
    if not st.session_state.schema_only_generated:
        st.info(
            "Generate outputs from the Main tab first."
        )
        return

    st.markdown("## Excel Sheet Mapping")

    rows = st.session_state.schema_only_excel_mapping_rows

    if not rows:
        st.info(
            "No mapping rows generated."
        )
        return

    st.markdown("### Sheet Map Abstract")

    abstract_rows = build_mapping_row_count_by_table(
        rows=rows,
        include_total=True,
    )

    if abstract_rows:
        st.dataframe(
            abstract_rows,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(
            "No table abstract rows available."
        )

    st.caption(
        "The TOTAL row matches the number of detailed mapping rows below."
    )

    st.markdown("### Sheet Mapping Details")

    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
    )


def main() -> None:
    st.set_page_config(
        page_title="Schema Listing Mapping",
        layout="wide",
    )

    initialize_directories()
    initialize_session_state()

    st.title(
        "Schema Listing Mapping"
    )

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