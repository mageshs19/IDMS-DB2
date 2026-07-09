import re

from idms_db2_converter.generators.cursors import CursorGenerator
from idms_db2_converter.generators.fetch_paragraphs import FetchParagraphGenerator
from idms_db2_converter.generators.host_variables import HostVariableGenerator
from idms_db2_converter.models import CobolAnalysis, SchemaModel
from idms_db2_converter.transformers.cobol_cleanup import CobolCleanup
from idms_db2_converter.transformers.dml_transformer import DmlTransformer
from idms_db2_converter.transformers.field_rewriter import FieldRewriter
from idms_db2_converter.transformers.operation_graph_transformer import (
    OperationGraphTransformer,
)
from idms_db2_converter.transformers.paragraph_rewriter import ParagraphRewriter


class RetrievalTransformer:
    """
    Transforms IDMS retrieval/update COBOL into DB2 embedded SQL COBOL.

    Retrieval behavior:
    - OBTAIN CALC becomes SELECT.
    - OBTAIN NEXT set navigation becomes cursor processing.
    - FIND FIRST lookup sets do not become declared cursors.
    - OBTAIN OWNER becomes keyed SELECT.
    - Existing generated DB2 blocks are removed before regeneration.
    - Existing incomplete FETCH paragraphs are removed and regenerated.
    - INIT-BIND-READY is renamed to INIT-DB2-SETUP.
    - PERFORM IDMS-STATUS lines are removed.
    - FINISH executable lines are removed unless already converted by DML logic.

    Update behavior:
    - STORE, MODIFY, ERASE are delegated to DmlTransformer.
    - DmlTransformer is called only when update DML exists.

    Host-variable optimization:
    - Does not add every schema relationship record.
    - Adds only records actually used by COBOL DML, set navigation,
      or field references.
    """

    PROCEDURE_DIVISION = re.compile(
        r"^\s*PROCEDURE\s+DIVISION\.",
        re.IGNORECASE | re.MULTILINE,
    )

    def __init__(
        self,
        schema: SchemaModel,
        analysis: CobolAnalysis,
    ) -> None:
        self.schema = schema
        self.analysis = analysis

    def transform(
        self,
        cobol: str,
        target_program: str | None = None,
    ) -> str:
        text = cobol

        if target_program and self.analysis.program_id:
            text = self._rename_program(
                text=text,
                source=self.analysis.program_id,
                target=target_program,
            )

        text = self._remove_existing_generated_db2_block(text)
        text = self._remove_idms_control_section(text)
        text = self._remove_schema_section(text)
        text = self._remove_idms_copybooks(text)

        operation_graph_transformer = OperationGraphTransformer(
            self.schema,
        )

        if operation_graph_transformer.has_graph():
            text = operation_graph_transformer.transform(text)

            used_cursor_sets = sorted(
                operation_graph_transformer.used_cursor_sets,
            )

        else:
            paragraph_rewriter = ParagraphRewriter(
                self.schema,
            )

            text = paragraph_rewriter.rewrite(text)

            used_cursor_sets = sorted(
                paragraph_rewriter.controlled_loop_sets,
            )

        used_cursor_sets = self._ensure_cursor_sets(
            used_cursor_sets,
        )

        dml_transformer = DmlTransformer(
            schema=self.schema,
            analysis=self.analysis,
        )

        if dml_transformer.has_update_dml():
            text = dml_transformer.transform(text)

        text = self._remove_existing_fetch_paragraphs(
            text=text,
            used_cursor_sets=used_cursor_sets,
        )

        text = self._insert_sql_declarations(
            text=text,
            used_cursor_sets=used_cursor_sets,
        )

        text = self._insert_fetch_paragraphs(
            text=text,
            used_cursor_sets=used_cursor_sets,
        )

        text = FieldRewriter(
            self.schema,
        ).rewrite(text)

        text = self._replace_init_bind_ready(text)
        text = self._remove_idms_status_perform(text)
        text = self._replace_finish(text)
        text = self._remove_bind_ready_lines(text)
        text = self._clean_end_processing(text)
        text = self._remove_idms_abort_paragraphs(text)
        text = self._remove_obsolete_set_walk_guard(text)
        text = self._cleanup_orphan_sqlcode_blocks(text)
        text = self._fix_paragraph_header_concatenation(text)
        text = self._normalize_formatting(text)

        text = CobolCleanup().clean(text)

        text = self._add_sql_error_paragraph(text)

        text = CobolCleanup().clean(text)

        return text

    def _rename_program(
        self,
        text: str,
        source: str,
        target: str,
    ) -> str:
        return re.sub(
            rf"(PROGRAM-ID\.\s*){re.escape(source)}(\.)?",
            rf"\1{target}.",
            text,
            flags=re.IGNORECASE,
        )

    def _remove_existing_generated_db2_block(
        self,
        text: str,
    ) -> str:
        pattern = re.compile(
            r"""
            \n\s*
            (?:EJECT\s*)?
            \*+\s*
            \n\s*\*\s*DB2\s+SQLCA,\s+HOST\s+VARIABLES,\s+AND\s+CURSORS\s*
            .*?
            (?=\n\s*PROCEDURE\s+DIVISION\.)
            """,
            re.IGNORECASE | re.DOTALL | re.VERBOSE,
        )

        return pattern.sub(
            "\n",
            text,
        )

    def _remove_idms_control_section(
        self,
        text: str,
    ) -> str:
        return re.sub(
            r"\n\s*IDMS-CONTROL\s+SECTION\..*?(?=\n\s*DATA\s+DIVISION\.)",
            "\n",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )

    def _remove_schema_section(
        self,
        text: str,
    ) -> str:
        return re.sub(
            r"\n\s*SCHEMA\s+SECTION\..*?(?=\n\s*FILE\s+SECTION\.)",
            "\n",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )

    def _remove_idms_copybooks(
        self,
        text: str,
    ) -> str:
        return re.sub(
            r"^\s*(?:01\s+)?COPY\s+IDMS\s+.*?\.?\s*$",
            "",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )

    def _ensure_cursor_sets(
        self,
        used_cursor_sets: list[str],
    ) -> list[str]:
        result = set(
            item.upper()
            for item in used_cursor_sets
            if item
        )

        for _, set_name in getattr(self.analysis, "obtain_next", []):
            if set_name:
                result.add(
                    set_name.upper(),
                )

        return sorted(result)

    def _insert_sql_declarations(
        self,
        text: str,
        used_cursor_sets: list[str],
    ) -> str:
        used_records = self._used_records(
            used_cursor_sets=used_cursor_sets,
        )

        host_variables = HostVariableGenerator().generate(
            self.schema,
            used_records,
        )

        cursors = CursorGenerator().generate(
            self.schema,
            used_cursor_sets,
        )

        block = "\n".join(
            [
                "",
                "    ***************************************************************",
                "    * DB2 SQLCA, HOST VARIABLES, AND CURSORS",
                "    ***************************************************************",
                host_variables,
                cursors,
                "",
            ]
        )

        return re.sub(
            r"(?=\n\s*PROCEDURE\s+DIVISION\.)",
            block,
            text,
            count=1,
            flags=re.IGNORECASE,
        )

    def _insert_fetch_paragraphs(
        self,
        text: str,
        used_cursor_sets: list[str],
    ) -> str:
        if not used_cursor_sets:
            return text

        fetch_paragraphs = FetchParagraphGenerator(
            self.schema,
        ).generate(
            used_cursor_sets,
        )

        if not fetch_paragraphs.strip():
            return text

        return re.sub(
            r"(?=\n\s*MAIN-LINE\.)",
            "\n" + fetch_paragraphs + "\n",
            text,
            count=1,
            flags=re.IGNORECASE,
        )

    def _remove_existing_fetch_paragraphs(
        self,
        text: str,
        used_cursor_sets: list[str],
    ) -> str:
        if not used_cursor_sets:
            return text

        for set_name in used_cursor_sets:
            fetch_name = f"FETCH-{set_name}".upper()

            pattern = re.compile(
                rf"""
                ^\s*{re.escape(fetch_name)}\.\s*
                .*?
                (?=
                    ^\s*MAIN-LINE\.\s*$
                    |
                    ^\s*[A-Z0-9-]+\.\s*$
                    |
                    \Z
                )
                """,
                re.IGNORECASE | re.MULTILINE | re.DOTALL | re.VERBOSE,
            )

            text = pattern.sub(
                "",
                text,
            )

        return text

    def _replace_init_bind_ready(
        self,
        text: str,
    ) -> str:
        text = re.sub(
            r"\bPERFORM\s+INIT-BIND-READY\b",
            "PERFORM INIT-DB2-SETUP",
            text,
            flags=re.IGNORECASE,
        )

        pattern = re.compile(
            r"""
            ^\s*INIT-BIND-READY\.\s*
            .*?
            (?=
                ^\s*INIT-FILES\.\s*$
                |
                \Z
            )
            """,
            re.IGNORECASE | re.MULTILINE | re.DOTALL | re.VERBOSE,
        )

        replacement = (
            "\n"
            "INIT-DB2-SETUP.\n"
            "       CONTINUE.\n"
        )

        return pattern.sub(
            replacement,
            text,
            count=1,
        )

    def _remove_idms_status_perform(
        self,
        text: str,
    ) -> str:
        return re.sub(
            r"^\s*PERFORM\s+IDMS-STATUS\.?\s*$",
            "",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )

    def _replace_finish(
        self,
        text: str,
    ) -> str:
        return re.sub(
            r"^\s*FINISH\.?\s*$",
            "",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )

    def _remove_bind_ready_lines(
        self,
        text: str,
    ) -> str:
        text = re.sub(
            r"^\s*BIND\s+[A-Z0-9-]+\.?\s*$",
            "",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )

        text = re.sub(
            r"^\s*READY\.?\s*$",
            "",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )

        return text

    def _clean_end_processing(
        self,
        text: str,
    ) -> str:
        text = re.sub(
            r"(\n\s*END-PROCESSING\.\s*)\n\s*CONTINUE\.\s*",
            r"\1",
            text,
            flags=re.IGNORECASE,
        )

        return text

    def _remove_idms_abort_paragraphs(
        self,
        text: str,
    ) -> str:
        return re.sub(
            r"\n\s*IDMS-ABORT\.\s*(?:\n\s*EXIT\.\s*)?\n\s*IDMS-ABORT-EXIT\.\s*(?:\n\s*EXIT\.\s*)?",
            "\n",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )

    def _remove_obsolete_set_walk_guard(
        self,
        text: str,
    ) -> str:
        pattern = re.compile(
            r"""
            \n\s*CONTINUE\.\s*
            \n\s*IF\s+SQLCODE\s*=\s*100\s*
            \n\s*GO\s+TO\s+[A-Z0-9-]+-EXIT\s*
            \n\s*ELSE\s*
            """,
            re.IGNORECASE | re.VERBOSE,
        )

        return pattern.sub(
            "\n       CONTINUE.\n",
            text,
        )

    def _cleanup_orphan_sqlcode_blocks(
        self,
        text: str,
    ) -> str:
        text = re.sub(
            r"""
            (\n\s*CONTINUE\.\s*)
            \n\s*IF\s+SQLCODE\s+NOT\s*=\s*0\s+AND\s+SQLCODE\s+NOT\s*=\s*100\s*
            \n\s*PERFORM\s+SQL-ERROR\s*
            \n\s*END-IF\.?
            """,
            r"\1",
            text,
            flags=re.IGNORECASE | re.VERBOSE,
        )

        text = re.sub(
            r"""
            (\n\s*END-PROCESSING\.\s*)
            \s*IF\s+SQLCODE\s+NOT\s*=\s*0\s+AND\s+SQLCODE\s+NOT\s*=\s*100\s*
            \n\s*PERFORM\s+SQL-ERROR\s*
            \n\s*END-IF\.?
            """,
            r"\1",
            text,
            flags=re.IGNORECASE | re.VERBOSE,
        )

        return text

    def _fix_paragraph_header_concatenation(
        self,
        text: str,
    ) -> str:
        text = re.sub(
            r"(\b[A-Z0-9-]+\.)\s*(IF\s+SQLCODE)",
            r"\1\n       \2",
            text,
            flags=re.IGNORECASE,
        )

        text = re.sub(
            r"(\b[A-Z0-9-]+\.)\s*(EXEC\s+SQL)",
            r"\1\n       \2",
            text,
            flags=re.IGNORECASE,
        )

        return text

    def _normalize_formatting(
        self,
        text: str,
    ) -> str:
        text = re.sub(
            r"\n{3,}",
            "\n\n",
            text,
        )

        text = re.sub(
            r"[ \t]+$",
            "",
            text,
            flags=re.MULTILINE,
        )

        return text

    def _add_sql_error_paragraph(
        self,
        text: str,
    ) -> str:
        if re.search(
            r"^\s*SQL-ERROR\.",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        ):
            return text

        return text.rstrip() + """

SQL-ERROR.
       MOVE SPACES TO ERR-LINE.
       MOVE 'SQL ERROR' TO ERR-MESS-OUT.
       MOVE ERR-DETAIL-LINE TO ERR-LINE.
       PERFORM U200-WRITE-ERR-LINE.

SQL-ERROR-EXIT.
       EXIT.
"""

    def _used_records(
        self,
        used_cursor_sets: list[str] | None = None,
    ) -> list[str]:
        records: set[str] = set()

        for record in getattr(self.analysis, "idms_records", []):
            self._add_record(
                records=records,
                record_name=record,
            )

        for record in getattr(self.analysis, "obtain_calc_records", []):
            self._add_record(
                records=records,
                record_name=record,
            )

        for record, _ in getattr(self.analysis, "obtain_next", []):
            self._add_record(
                records=records,
                record_name=record,
            )

        for record in getattr(self.analysis, "store_records", []):
            self._add_record(
                records=records,
                record_name=record,
            )

        for record in getattr(self.analysis, "modify_records", []):
            self._add_record(
                records=records,
                record_name=record,
            )

        for record in getattr(self.analysis, "erase_records", []):
            self._add_record(
                records=records,
                record_name=record,
            )

        self._add_relationship_records_for_used_sets(
            records=records,
            used_cursor_sets=used_cursor_sets or [],
        )

        self._add_field_reference_records(
            records=records,
        )

        return sorted(records)

    def _add_record(
        self,
        records: set[str],
        record_name: str | None,
    ) -> None:
        if not record_name:
            return

        value = str(record_name).strip().upper()

        if not value:
            return

        records.add(
            value,
        )

    def _used_set_names(
        self,
        used_cursor_sets: list[str],
    ) -> set[str]:
        set_names: set[str] = set()

        for set_name in used_cursor_sets:
            if set_name:
                set_names.add(
                    set_name.upper(),
                )

        for _, set_name in getattr(self.analysis, "obtain_next", []):
            if set_name:
                set_names.add(
                    set_name.upper(),
                )

        for set_name in getattr(self.analysis, "obtain_owner_sets", []):
            if set_name:
                set_names.add(
                    set_name.upper(),
                )

        for set_name in getattr(self.analysis, "find_first_sets", []):
            if set_name:
                set_names.add(
                    set_name.upper(),
                )

        return set_names

    def _add_relationship_records_for_used_sets(
        self,
        records: set[str],
        used_cursor_sets: list[str],
    ) -> None:
        used_set_names = self._used_set_names(
            used_cursor_sets=used_cursor_sets,
        )

        if not used_set_names:
            return

        for set_name in used_set_names:
            relationship = self.schema.relationships.get(
                set_name,
            )

            if not relationship:
                continue

            self._add_record(
                records=records,
                record_name=relationship.parent_record,
            )

            self._add_record(
                records=records,
                record_name=relationship.child_record,
            )

    def _add_field_reference_records(
        self,
        records: set[str],
    ) -> None:
        field_references = (
            getattr(self.analysis, "field_references", [])
            or getattr(self.analysis, "idms_fields", [])
            or []
        )

        for field_name in field_references:
            for record_name in self._record_names_from_field_reference(
                field_name=field_name,
            ):
                self._add_record(
                    records=records,
                    record_name=record_name,
                )

    def _record_names_from_field_reference(
        self,
        field_name: str,
    ) -> list[str]:
        result: list[str] = []

        if not field_name:
            return result

        field_map = getattr(
            self.schema,
            "field_map",
            {},
        )

        meta = field_map.get(
            field_name.upper(),
        )

        if not meta:
            return result

        record = (
            meta.get("record")
            or meta.get("table")
            or meta.get("record_name")
            or meta.get("table_name")
        )

        if record:
            result.append(
                str(record).upper(),
            )

        host = meta.get(
            "host",
        )

        if host:
            host_record = self._record_name_from_host(
                str(host),
            )

            if host_record:
                result.append(
                    host_record,
                )

        column_record = meta.get(
            "logical_record",
        )

        if column_record:
            result.append(
                str(column_record).upper(),
            )

        return result

    def _record_name_from_host(
        self,
        host: str,
    ) -> str | None:
        normalized_host = self._normalize_name(
            host,
        )

        if not normalized_host.startswith("HV-"):
            return None

        candidates: list[str] = []

        candidates.extend(
            list(getattr(self.schema, "record_table_map", {}).keys()),
        )

        candidates.extend(
            list(getattr(self.schema, "records", {}).keys()),
        )

        candidates = sorted(
            set(
                str(candidate).upper()
                for candidate in candidates
                if candidate
            ),
            key=len,
            reverse=True,
        )

        for candidate in candidates:
            normalized_candidate = self._normalize_name(
                candidate,
            )

            prefix = f"HV-{normalized_candidate}-"

            if normalized_host.startswith(prefix):
                return candidate.upper()

        return None

    def _normalize_name(
        self,
        value: str,
    ) -> str:
        return (
            str(value)
            .strip()
            .upper()
            .replace("_", "-")
            .replace(" ", "-")
        )