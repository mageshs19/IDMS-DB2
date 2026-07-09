import re

from idms_db2_converter.generators.fetch_paragraphs import FetchParagraphGenerator
from idms_db2_converter.generators.naming import Naming
from idms_db2_converter.generators.sql_snippets import SqlSnippets
from idms_db2_converter.models import SchemaModel
from idms_db2_converter.transformers.structured_blocks import StructuredBlocks


class ParagraphRewriter:
    def __init__(self, schema: SchemaModel):
        self.schema = schema
        self.sql = SqlSnippets(schema)
        self.fetch_generator = FetchParagraphGenerator(schema)
        self.controlled_loop_sets: set[str] = set()

    def rewrite(self, text: str) -> str:
        text = self._rewrite_cursor_loop_blocks(text)
        text = self._rewrite_find_first_owner_chain_blocks(text)
        text = self._rewrite_empty_else_obtain_owner_blocks(text)
        text = self._rewrite_empty_else_find_first_blocks(text)
        text = self._rewrite_obtain_calc_if_blocks(text)
        text = self._rewrite_remaining_obtain_calc(text)
        text = self._rewrite_remaining_obtain_next(text)
        text = self._rewrite_remaining_find_first(text)
        text = self._rewrite_remaining_obtain_owner(text)
        text = self._rewrite_status_tokens(text)
        return text

    def _rewrite_cursor_loop_blocks(self, text: str) -> str:
        for set_name in self.schema.relationships:
            text = self._rewrite_cursor_loop_for_set(text, set_name)

        return text

    def _rewrite_cursor_loop_for_set(self, text: str, set_name: str) -> str:
        pattern = re.compile(
            rf"""
            IF\s+{re.escape(set_name)}\s+IS\s+NOT\s+EMPTY\s+THEN
            (?P<before_loop>.*?)
            PERFORM\s+(?P<walk>[A-Z0-9-]+)\s+THRU\s+(?P<exit>[A-Z0-9-]+)
            \s+UNTIL\s+DB-END-OF-SET
            \s+ELSE
            (?P<empty_body>.*?)
            (?=\.\s*READ|\.\s*[A-Z0-9-]+\.)
            """,
            re.IGNORECASE | re.DOTALL | re.VERBOSE,
        )

        def replace(match: re.Match) -> str:
            self.controlled_loop_sets.add(set_name.upper())

            return StructuredBlocks.cursor_loop_block(
                cursor_name=Naming.cursor(set_name),
                fetch_paragraph=self.fetch_generator.paragraph_name(set_name),
                empty_body=self._clean_block(match.group("empty_body")),
                before_loop_body=self._clean_block(match.group("before_loop")),
                walk_paragraph=match.group("walk").upper(),
                walk_exit=match.group("exit").upper(),
                indent=7,
            )

        return pattern.sub(replace, text)

    def _rewrite_find_first_owner_chain_blocks(self, text: str) -> str:
        for first_set in self.schema.relationships:
            for owner_set in self.schema.relationships:
                text = self._rewrite_one_find_first_owner_chain(
                    text=text,
                    first_set=first_set,
                    owner_set=owner_set,
                )

        return text

    def _rewrite_one_find_first_owner_chain(
        self,
        text: str,
        first_set: str,
        owner_set: str,
    ) -> str:
        pattern = re.compile(
            rf"""
            IF\s+{re.escape(first_set)}\s+IS\s+EMPTY
            (?P<first_empty>.*?)
            ELSE\s+
            FIND\s+FIRST\s+WITHIN\s+{re.escape(first_set)}\.?
            (?P<after_find>.*?)
            IF\s+NOT\s+{re.escape(owner_set)}\s+MEMBER
            (?P<owner_missing>.*?)
            ELSE\s+
            OBTAIN\s+OWNER\s+WITHIN\s+{re.escape(owner_set)}\.?
            (?P<success>.*?)
            (?=
                \n\s*IF\s+[A-Z0-9-]+\s+IS\s+EMPTY
                |
                \n\s*MOVE\s+EMP-DETAIL-LINE
                |
                \n\s*PERFORM\s+
                |
                \n\s*[A-Z0-9-]+-EXIT\.
            )
            """,
            re.IGNORECASE | re.DOTALL | re.VERBOSE,
        )

        def replace(match: re.Match) -> str:
            first_empty = self._remove_idms_status_lines(
                self._clean_block(match.group("first_empty"))
            )
            owner_missing = self._remove_idms_status_lines(
                self._clean_block(match.group("owner_missing"))
            )
            success = self._remove_idms_status_lines(
                self._clean_block(match.group("success"))
            )

            if not success:
                success = "CONTINUE"

            return StructuredBlocks.select_first_then_owner_chain(
                first_select_sql=self.sql.select_first_child_for_set(first_set),
                owner_select_sql=self.sql.select_for_owner(owner_set),
                first_not_found_body=first_empty,
                owner_not_found_body=owner_missing,
                success_body=success,
                indent=7,
            )

        return pattern.sub(replace, text)

    def _rewrite_empty_else_obtain_owner_blocks(self, text: str) -> str:
        for set_name in self.schema.relationships:
            pattern = re.compile(
                rf"""
                IF\s+{re.escape(set_name)}\s+IS\s+EMPTY
                (?P<empty_body>.*?)
                ELSE\s+
                OBTAIN\s+OWNER\s+WITHIN\s+{re.escape(set_name)}\.?
                (?P<success_body>.*?)
                (?=
                    \n\s*MOVE\s+EMP-DETAIL-LINE
                    |
                    \n\s*PERFORM\s+
                    |
                    \n\s*[A-Z0-9-]+-EXIT\.
                )
                """,
                re.IGNORECASE | re.DOTALL | re.VERBOSE,
            )

            def replace(match: re.Match, set_name=set_name) -> str:
                empty_body = self._remove_idms_status_lines(
                    self._clean_block(match.group("empty_body"))
                )
                success_body = self._remove_idms_status_lines(
                    self._clean_block(match.group("success_body"))
                )

                if not success_body:
                    success_body = "CONTINUE"

                indicator = self.sql.nullable_fk_indicator_for_set(set_name)

                if indicator:
                    return StructuredBlocks.nullable_owner_block(
                        null_indicator=indicator,
                        null_body=empty_body,
                        owner_select_sql=self.sql.select_for_owner(set_name),
                        success_body=success_body,
                        fallback_body=empty_body,
                        indent=7,
                    )

                return StructuredBlocks.owner_select_block(
                    owner_select_sql=self.sql.select_for_owner(set_name),
                    success_body=success_body,
                    fallback_body=empty_body,
                    indent=7,
                )

            text = pattern.sub(replace, text)

        return text

    def _rewrite_empty_else_find_first_blocks(self, text: str) -> str:
        for set_name in self.schema.relationships:
            pattern = re.compile(
                rf"""
                IF\s+{re.escape(set_name)}\s+IS\s+EMPTY
                (?P<empty_body>.*?)
                ELSE\s+
                FIND\s+FIRST\s+WITHIN\s+{re.escape(set_name)}\.?
                (?P<success_body>.*?)
                (?=
                    \n\s*IF\s+[A-Z0-9-]+\s+IS\s+EMPTY
                    |
                    \n\s*MOVE\s+EMP-DETAIL-LINE
                    |
                    \n\s*PERFORM\s+
                    |
                    \n\s*[A-Z0-9-]+-EXIT\.
                )
                """,
                re.IGNORECASE | re.DOTALL | re.VERBOSE,
            )

            def replace(match: re.Match, set_name=set_name) -> str:
                empty_body = self._remove_idms_status_lines(
                    self._clean_block(match.group("empty_body"))
                )
                success_body = self._remove_idms_status_lines(
                    self._clean_block(match.group("success_body"))
                )

                if not success_body:
                    success_body = "CONTINUE"

                return StructuredBlocks.sqlcode_select_block(
                    sql=self.sql.select_first_child_for_set(set_name),
                    not_found_body=empty_body,
                    success_body=success_body,
                    indent=7,
                )

            text = pattern.sub(replace, text)

        return text

    def _rewrite_obtain_calc_if_blocks(self, text: str) -> str:
        pattern = re.compile(
            r"""
            OBTAIN\s+CALC\s+(?P<record>[A-Z0-9-]+)\.?
            \s+
            IF\s+DB-REC-NOT-FOUND\s+THEN
            (?P<not_found>.*?)
            ELSE
            (?P<success>.*?)
            (?=\n\s*READ\s+)
            """,
            re.IGNORECASE | re.DOTALL | re.VERBOSE,
        )

        def replace(match: re.Match) -> str:
            record = match.group("record").upper()
            not_found = self._remove_idms_status_lines(
                self._clean_block(match.group("not_found"))
            )
            success = self._remove_idms_status_lines(
                self._clean_block(match.group("success"))
            )

            return StructuredBlocks.sqlcode_select_block(
                sql=self.sql.select_for_record_by_pk(record),
                not_found_body=not_found,
                success_body=success,
                indent=7,
            )

        return pattern.sub(replace, text)

    def _rewrite_remaining_obtain_calc(self, text: str) -> str:
        pattern = re.compile(
            r"^\s*OBTAIN\s+CALC\s+([A-Z0-9-]+)\.?\s*$",
            re.IGNORECASE | re.MULTILINE,
        )

        return pattern.sub(
            lambda m: self.sql.select_for_record_by_pk(m.group(1).upper()),
            text,
        )

    def _rewrite_remaining_obtain_next(self, text: str) -> str:
        pattern = re.compile(
            r"^\s*OBTAIN\s+NEXT\s+([A-Z0-9-]+)\s+WITHIN\s+([A-Z0-9-]+)\.?\s*$",
            re.IGNORECASE | re.MULTILINE,
        )

        def replace(match: re.Match) -> str:
            set_name = match.group(2).upper()

            if set_name in self.controlled_loop_sets:
                return "       CONTINUE."

            return f"       PERFORM {self.fetch_generator.paragraph_name(set_name)}"

        return pattern.sub(replace, text)

    def _rewrite_remaining_find_first(self, text: str) -> str:
        pattern = re.compile(
            r"^\s*FIND\s+FIRST\s+WITHIN\s+([A-Z0-9-]+)\.?\s*$",
            re.IGNORECASE | re.MULTILINE,
        )

        return pattern.sub(
            lambda m: self.sql.select_first_child_for_set(m.group(1).upper()),
            text,
        )

    def _rewrite_remaining_obtain_owner(self, text: str) -> str:
        pattern = re.compile(
            r"^\s*OBTAIN\s+OWNER\s+WITHIN\s+([A-Z0-9-]+)\.?\s*$",
            re.IGNORECASE | re.MULTILINE,
        )

        return pattern.sub(
            lambda m: self.sql.select_for_owner(m.group(1).upper()),
            text,
        )

    def _rewrite_status_tokens(self, text: str) -> str:
        text = re.sub(
            r"\bDB-REC-NOT-FOUND\b",
            "SQLCODE = 100",
            text,
            flags=re.IGNORECASE,
        )

        text = re.sub(
            r"\bDB-END-OF-SET\b",
            "SQLCODE = 100",
            text,
            flags=re.IGNORECASE,
        )

        text = re.sub(
            r"IF\s+NOT\s+[A-Z0-9-]+\s+MEMBER",
            "IF SQLCODE = 100",
            text,
            flags=re.IGNORECASE,
        )

        return text

    def _remove_idms_status_lines(self, text: str) -> str:
        text = re.sub(
            r"^\s*PERFORM\s+IDMS-STATUS\.?\s*$",
            "",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )

        text = re.sub(
            r"^\s*IF SQLCODE NOT = 0 AND SQLCODE NOT = 100\s*"
            r"\n\s*PERFORM SQL-ERROR\s*"
            r"\n\s*END-IF\.?\s*$",
            "",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )

        return text.strip()

    def _clean_block(self, value: str) -> str:
        value = value.strip()

        if value.endswith("."):
            value = value[:-1].rstrip()

        return value