# src/idms_modernizer/app.py

from pathlib import Path
from time import perf_counter

import streamlit as st

from idms_modernizer.core.config import settings
from idms_modernizer.core.utils import ensure_directory
from idms_modernizer.core.constants import (
    ER_DIAGRAM_FILE,
    PHASE2_METADATA_FILE,
)
from idms_modernizer.parsers.cobol_pdf_extractor import CobolPdfExtractor
from idms_modernizer.services.metadata_service import MetadataService
from idms_modernizer.services.canonical_schema_builder import (
    CanonicalSchemaBuilder,
)
from idms_modernizer.services.canonical_reconciler import (
    CanonicalReconciler,
)
from idms_modernizer.services.db2_model_builder import DB2ModelBuilder
from idms_modernizer.services.phase2_metadata_generator import (
    Phase2MetadataGenerator,
)
from idms_modernizer.services.phase2_conversion_bridge import (
    Phase2ConversionBridge,
)
from idms_modernizer.services.er_diagram_generator import (
    generate_er_diagram,
)
from idms_modernizer.generators.ddl_generator import DDLGenerator
from idms_modernizer.services.excel_sheet_mapping_service import (
    ExcelSheetMappingService,
)


def log_timing(
    timings: list[str],
    label: str,
    start_time: float,
) -> float:
    elapsed = perf_counter() - start_time
    message = f"{label}: {elapsed:.2f} seconds"

    print(message)

    timings.append(message)

    return perf_counter()


def total_timing_only() -> str:
    timings = st.session_state.get(
        "generation_timings",
        [],
    )

    for item in reversed(timings):
        if item.startswith("TOTAL: "):
            return item

    return ""


def split_phase2_timings(
    validation_messages: list[str],
    timings: list[str],
) -> list[str]:
    cleaned_messages: list[str] = []

    for message in validation_messages:
        if message.startswith("Phase 2 - "):
            timings.append(message)
        else:
            cleaned_messages.append(message)

    return cleaned_messages


def initialize_directories() -> None:
    ensure_directory(settings.input_dir)
    ensure_directory(settings.output_dir)
    ensure_directory(settings.temp_dir)


def initialize_session_state() -> None:
    defaults = {
        "generated": False,
        "schema_path": "",
        "cobol_pdf_path": "",
        "cobol_text": "",
        "converted_cobol": "",
        "ddl_text": "",
        "canonical_json": "",
        "phase2_metadata_json": "",
        "metadata": None,
        "canonical_schema": None,
        "db2_model": None,
        "relationships": [],
        "all_sets": [],
        "record_count": 0,
        "set_count": 0,
        "relationship_count": 0,
        "validation_messages": [],
        "generation_warnings": [],
        "generation_timings": [],
        "er_png_path": "",
        "er_image_bytes": None,
        "output_files": {},
        "excel_mapping_rows": [],
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_outputs() -> None:
    st.session_state.generated = False
    st.session_state.schema_path = ""
    st.session_state.cobol_pdf_path = ""
    st.session_state.cobol_text = ""
    st.session_state.converted_cobol = ""
    st.session_state.ddl_text = ""
    st.session_state.canonical_json = ""
    st.session_state.phase2_metadata_json = ""
    st.session_state.metadata = None
    st.session_state.canonical_schema = None
    st.session_state.db2_model = None
    st.session_state.relationships = []
    st.session_state.all_sets = []
    st.session_state.record_count = 0
    st.session_state.set_count = 0
    st.session_state.relationship_count = 0
    st.session_state.validation_messages = []
    st.session_state.generation_warnings = []
    st.session_state.generation_timings = []
    st.session_state.er_png_path = ""
    st.session_state.er_image_bytes = None
    st.session_state.output_files = {}
    st.session_state.excel_mapping_rows = []


def save_uploaded_file(
    uploaded_file,
    target_folder: str,
) -> str:
    target_dir = Path(target_folder)

    target_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    target_path = target_dir / uploaded_file.name

    with open(target_path, "wb") as file:
        file.write(uploaded_file.getbuffer())

    return str(target_path)


def write_output_file(
    output_dir: Path,
    file_name: str,
    content: str,
    encoding: str = "utf-8",
) -> Path:
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = output_dir / file_name

    path.write_text(
        content,
        encoding=encoding,
    )

    return path


def build_sets_summary(metadata) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    for relationship in metadata.relationships:
        rows.append(
            {
                "set_name": getattr(relationship, "set_name", ""),
                "owner_record": getattr(relationship, "owner_record", ""),
                "member_record": getattr(relationship, "member_record", ""),
                "cardinality": getattr(relationship, "cardinality", ""),
            }
        )

    return rows


def generate_outputs(
    schema_pdf,
    cobol_pdf,
) -> None:
    total_start = perf_counter()
    step_start = perf_counter()
    timings: list[str] = []

    reset_outputs()

    warnings = []

    schema_path = save_uploaded_file(
        schema_pdf,
        settings.input_dir,
    )

    cobol_pdf_path = save_uploaded_file(
        cobol_pdf,
        settings.input_dir,
    )

    step_start = log_timing(
        timings,
        "Save uploaded files",
        step_start,
    )

    metadata_service = MetadataService()

    metadata = metadata_service.build_metadata(
        schema_path,
    )

    step_start = log_timing(
        timings,
        "Build metadata from schema PDF",
        step_start,
    )

    canonical_builder = CanonicalSchemaBuilder()

    canonical_schema = canonical_builder.build(
        metadata,
    )

    step_start = log_timing(
        timings,
        "Build canonical schema",
        step_start,
    )

    reconciler = CanonicalReconciler()

    canonical_schema = reconciler.reconcile(
        canonical_schema=canonical_schema,
        metadata=metadata,
    )

    step_start = log_timing(
        timings,
        "Reconcile canonical schema",
        step_start,
    )

    db2_builder = DB2ModelBuilder()

    db2_model = db2_builder.build(
        canonical_schema,
    )

    step_start = log_timing(
        timings,
        "Build DB2 model",
        step_start,
    )

    ddl_generator = DDLGenerator()

    ddl_text = ddl_generator.generate(
        db2_model,
    )

    step_start = log_timing(
        timings,
        "Generate DB2 DDL",
        step_start,
    )

    excel_mapping_service = ExcelSheetMappingService()

    excel_mapping_rows = excel_mapping_service.build(
        metadata=metadata,
        db2_model=db2_model,
    )

    step_start = log_timing(
        timings,
        "Generate Excel Sheet Mapping",
        step_start,
    )

    phase2_metadata_generator = Phase2MetadataGenerator()

    phase2_metadata_json = phase2_metadata_generator.generate_json(
        canonical_schema=canonical_schema,
        db2_model=db2_model,
        metadata=metadata,
    )

    step_start = log_timing(
        timings,
        "Generate Phase 2 metadata JSON",
        step_start,
    )

    canonical_json = canonical_schema.model_dump_json(
        indent=2,
    )

    step_start = log_timing(
        timings,
        "Generate canonical JSON",
        step_start,
    )

    cobol_extractor = CobolPdfExtractor()

    cobol_text = cobol_extractor.extract_text(
        cobol_pdf_path,
    )

    step_start = log_timing(
        timings,
        "Extract COBOL PDF text",
        step_start,
    )

    phase2_bridge = Phase2ConversionBridge()

    converted_cobol, validation_messages = phase2_bridge.convert(
        cobol_text=cobol_text,
        canonical_json=canonical_json,
        phase2_metadata_json=phase2_metadata_json,
        ddl_text=ddl_text,
        idms_schema_text=None,
        relationship_overrides_json=None,
        target_program=None,
        use_ddl=True,
        use_idms_schema=False,
        use_overrides=False,
    )

    validation_messages = split_phase2_timings(
        validation_messages=validation_messages,
        timings=timings,
    )

    step_start = log_timing(
        timings,
        "Convert COBOL to DB2 COBOL",
        step_start,
    )

    relationships = metadata.relationships

    all_sets = build_sets_summary(
        metadata,
    )

    step_start = log_timing(
        timings,
        "Build relationship and set summaries",
        step_start,
    )

    output_dir = Path(
        settings.output_dir,
    )

    output_files = {}

    output_files["ddl"] = write_output_file(
        output_dir=output_dir,
        file_name="db2_ddl.sql",
        content=ddl_text,
    )

    output_files["canonical"] = write_output_file(
        output_dir=output_dir,
        file_name="canonical_model.json",
        content=canonical_json,
    )

    output_files["phase2_metadata"] = write_output_file(
        output_dir=output_dir,
        file_name=PHASE2_METADATA_FILE,
        content=phase2_metadata_json,
    )

    output_files["converted_cobol"] = write_output_file(
        output_dir=output_dir,
        file_name="converted_db2_cobol.cbl",
        content=converted_cobol,
    )

    step_start = log_timing(
        timings,
        "Write output files",
        step_start,
    )

    er_png_path = ""
    er_image_bytes = None

    try:
        er_path = output_dir / ER_DIAGRAM_FILE

        er_png_path = generate_er_diagram(
            metadata,
            str(er_path),
        )

        with open(er_png_path, "rb") as image_file:
            er_image_bytes = image_file.read()

        output_files["er_diagram"] = Path(er_png_path)

    except Exception as ex:
        warnings.append(
            "ER diagram was not generated. "
            "Graphviz may not be installed or configured. "
            f"Details: {ex}"
        )

    step_start = log_timing(
        timings,
        "ER diagram generation",
        step_start,
    )

    st.session_state.generated = True
    st.session_state.schema_path = schema_path
    st.session_state.cobol_pdf_path = cobol_pdf_path
    st.session_state.metadata = metadata
    st.session_state.canonical_schema = canonical_schema
    st.session_state.db2_model = db2_model
    st.session_state.ddl_text = ddl_text
    st.session_state.canonical_json = canonical_json
    st.session_state.phase2_metadata_json = phase2_metadata_json
    st.session_state.cobol_text = cobol_text
    st.session_state.converted_cobol = converted_cobol
    st.session_state.relationships = relationships
    st.session_state.all_sets = all_sets
    st.session_state.record_count = len(metadata.records)
    st.session_state.set_count = len(all_sets)
    st.session_state.relationship_count = len(relationships)
    st.session_state.validation_messages = validation_messages
    st.session_state.generation_warnings = warnings
    st.session_state.er_png_path = er_png_path
    st.session_state.er_image_bytes = er_image_bytes
    st.session_state.output_files = output_files
    st.session_state.excel_mapping_rows = excel_mapping_rows

    total_elapsed = perf_counter() - total_start

    timings.append(
        f"TOTAL: {total_elapsed:.2f} seconds",
    )

    print("=" * 80)
    print("GENERATION TIMINGS")
    print("=" * 80)

    for item in timings:
        print(item)

    st.session_state.generation_timings = timings


def render_download_button(
    label: str,
    path,
    file_name: str,
    mime: str,
) -> None:
    if not path:
        st.button(
            label,
            disabled=True,
            use_container_width=True,
        )
        return

    path = Path(path)

    if not path.exists():
        st.button(
            label,
            disabled=True,
            use_container_width=True,
        )
        return

    with open(path, "rb") as file:
        st.download_button(
            label=label,
            data=file.read(),
            file_name=file_name,
            mime=mime,
            use_container_width=True,
        )


def render_download_buttons() -> None:
    output_files = st.session_state.output_files

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        render_download_button(
            label="DB2 DDL",
            path=output_files.get("ddl"),
            file_name="db2_ddl.sql",
            mime="text/plain",
        )

    with col2:
        render_download_button(
            label="Phase 2 Metadata",
            path=output_files.get("phase2_metadata"),
            file_name=PHASE2_METADATA_FILE,
            mime="application/json",
        )

    with col3:
        render_download_button(
            label="Canonical JSON",
            path=output_files.get("canonical"),
            file_name="canonical_model.json",
            mime="application/json",
        )

    with col4:
        if st.session_state.er_image_bytes:
            st.download_button(
                label="ER Diagram",
                data=st.session_state.er_image_bytes,
                file_name=ER_DIAGRAM_FILE,
                mime="image/png",
                use_container_width=True,
            )
        else:
            st.button(
                "ER Diagram",
                disabled=True,
                use_container_width=True,
            )

    with col5:
        render_download_button(
            label="DB2 COBOL",
            path=output_files.get("converted_cobol"),
            file_name="converted_db2_cobol.cbl",
            mime="text/plain",
        )


def get_total_generation_time() -> str:
    total_timing = total_timing_only()

    if not total_timing:
        return ""

    return total_timing.replace(
        "TOTAL:",
        "",
    ).strip()


def render_status_panel() -> None:
    if not st.session_state.generated:
        return

    total_time = get_total_generation_time()

    if total_time:
        st.success(
            f"Generation completed in {total_time}",
        )

    if st.session_state.generation_warnings:
        with st.expander(
            "Generation Warnings",
            expanded=False,
        ):
            for warning in st.session_state.generation_warnings:
                st.warning(warning)

    if not st.session_state.validation_messages:
        st.success(
            "COBOL conversion validation passed.",
        )
    else:
        st.warning(
            "COBOL conversion completed with validation messages. "
            "Open the Validation tab for details.",
        )


def render_main_tab() -> None:
    st.markdown("## Generate Modernization Outputs")

    st.info(
        "Upload the Schema Listing PDF and COBOL Code PDF to generate DB2 "
        "DDL, metadata, ER diagram, Excel Sheet Mapping, and converted DB2 COBOL."
    )

    col1, col2 = st.columns(2)

    with col1:
        schema_pdf = st.file_uploader(
            "Schema Listing PDF",
            type=["pdf"],
            key="schema_listing_pdf",
        )

    with col2:
        cobol_pdf = st.file_uploader(
            "COBOL Code PDF",
            type=["pdf"],
            key="cobol_code_pdf",
        )

    generate_clicked = st.button(
        "Generate Outputs",
        type="primary",
        use_container_width=True,
    )

    if generate_clicked:
        if schema_pdf is None:
            st.error(
                "Please upload the Schema Listing PDF.",
            )
            st.stop()

        if cobol_pdf is None:
            st.error(
                "Please upload the COBOL Code PDF.",
            )
            st.stop()

        with st.spinner(
            "Processing schema, generating DB2 artifacts, and converting COBOL..."
        ):
            try:
                generate_outputs(
                    schema_pdf=schema_pdf,
                    cobol_pdf=cobol_pdf,
                )

                st.success(
                    "Generation completed successfully.",
                )

            except Exception as ex:
                st.error(
                    "Generation failed.",
                )
                st.exception(ex)
                st.stop()

    if st.session_state.generated:
        st.markdown("### Output Status")

        col_a, col_b = st.columns(2)

        with col_a:
            st.write(
                f"Schema PDF: `{st.session_state.schema_path}`",
            )

        with col_b:
            st.write(
                f"COBOL PDF: `{st.session_state.cobol_pdf_path}`",
            )

        render_status_panel()
        render_download_buttons()


def render_metadata_overview_tab() -> None:
    if not st.session_state.generated:
        st.info(
            "Generate outputs from the Main tab first.",
        )
        return

    st.markdown("## Metadata Overview")

    st.markdown("### Summary")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            "Records",
            st.session_state.record_count,
        )

    with col2:
        st.metric(
            "Sets",
            st.session_state.set_count,
        )

    with col3:
        st.metric(
            "Relationships",
            st.session_state.relationship_count,
        )

    st.divider()

    st.markdown("### Detected Sets")

    st.json(
        st.session_state.all_sets,
    )


def render_ddl_tab() -> None:
    if not st.session_state.generated:
        st.info(
            "Generate outputs from the Main tab first.",
        )
        return

    st.markdown("## DB2 DDL Preview")

    st.code(
        st.session_state.ddl_text,
        language="sql",
    )


def render_excel_sheet_mapping_tab() -> None:
    if not st.session_state.generated:
        st.info(
            "Generate outputs from the Main tab first.",
        )
        return

    st.markdown("## Excel Sheet Mapping")

    rows = st.session_state.excel_mapping_rows

    if not rows:
        st.info(
            "No mapping rows generated.",
        )
        return

    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
    )


def render_phase2_metadata_tab() -> None:
    if not st.session_state.generated:
        st.info(
            "Generate outputs from the Main tab first.",
        )
        return

    st.markdown("## Phase 2 Metadata Preview")

    st.code(
        st.session_state.phase2_metadata_json,
        language="json",
    )


def render_er_diagram_tab() -> None:
    if not st.session_state.generated:
        st.info(
            "Generate outputs from the Main tab first.",
        )
        return

    st.markdown("## ER Diagram")

    if st.session_state.er_image_bytes:
        st.image(
            st.session_state.er_image_bytes,
        )
    else:
        st.warning(
            "ER diagram was not generated. Graphviz may not be installed "
            "or configured.",
        )


def render_converted_cobol_tab() -> None:
    if not st.session_state.generated:
        st.info(
            "Generate outputs from the Main tab first.",
        )
        return

    st.markdown("## Converted DB2 COBOL")

    if not st.session_state.converted_cobol:
        st.warning(
            "Converted COBOL output is empty or conversion failed.",
        )

    st.text_area(
        "Final DB2 COBOL Code",
        value=st.session_state.converted_cobol,
        height=750,
    )


def render_validation_tab() -> None:
    if not st.session_state.generated:
        st.info(
            "Generate outputs from the Main tab first.",
        )
        return

    st.markdown("## Validation & Warnings")

    if st.session_state.get("generation_timings"):
        st.markdown("### Generation Timings")

        for timing in st.session_state.generation_timings:
            st.write(
                f"- {timing}",
            )

    has_generation_warnings = bool(
        st.session_state.generation_warnings,
    )

    has_validation_messages = bool(
        st.session_state.validation_messages,
    )

    if has_generation_warnings:
        st.markdown("### Generation Warnings")

        for warning in st.session_state.generation_warnings:
            st.warning(
                warning,
            )

    if has_validation_messages:
        st.markdown("### COBOL Conversion Validation Messages")

        for message in st.session_state.validation_messages:
            st.write(
                f"- {message}",
            )

    if not has_generation_warnings and not has_validation_messages:
        st.success(
            "No warnings or validation messages.",
        )


def main() -> None:
    initialize_directories()
    initialize_session_state()

    st.set_page_config(
        page_title="IDMS DB2 Modernizer",
        layout="wide",
    )

    st.title(
        "IDMS > DB2 Modernizer",
    )

    st.caption(
        "Generate DB2 DDL, Phase 2 metadata, canonical JSON, ER diagram, "
        "Excel Sheet Mapping, and converted DB2 COBOL from uploaded PDFs."
    )

    tabs = st.tabs(
        [
            "Main",
            "Metadata Overview",
            "DB2 DDL",
            "Excel Sheet Mapping",
            "Phase 2 Metadata",
            "ER Diagram",
            "Converted DB2 COBOL",
            "Validation",
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

    with tabs[4]:
        render_phase2_metadata_tab()

    with tabs[5]:
        render_er_diagram_tab()

    with tabs[6]:
        render_converted_cobol_tab()

    with tabs[7]:
        render_validation_tab()


if __name__ == "__main__":
    main()