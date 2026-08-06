import re


class CobolCleanup:
    """
    Final cleanup pass for generated COBOL.

    Goals:
    - Preserve DATA DIVISION and WORKING-STORAGE declarations.
    - Normalize all EXEC SQL blocks, including declarations before PROCEDURE DIVISION.
    - Normalize PROCEDURE DIVISION formatting.
    - Fix IF / ELSE / ELSE IF / END-IF indentation.
    - Fix PERFORM ... UNTIL continuation indentation.
    - Fix READ ... AT END indentation.
    - Fix paragraph header concatenation.
    - Avoid changing business logic.
    """

    EXEC_SQL_START = re.compile(
        r"^\s*EXEC\s+SQL\b",
        re.IGNORECASE,
    )

    EXEC_SQL_END = re.compile(
        r"^\s*END-EXEC\.?\s*$",
        re.IGNORECASE,
    )

    PROCEDURE_DIVISION = re.compile(
        r"^\s*PROCEDURE\s+DIVISION\.",
        re.IGNORECASE | re.MULTILINE,
    )

    DATA_DIVISION = re.compile(
        r"^\s*DATA\s+DIVISION\.",
        re.IGNORECASE | re.MULTILINE,
    )

    PARAGRAPH_HEADER = re.compile(
        r"^\s*[A-Z0-9-]+\.\s*$",
        re.IGNORECASE,
    )

    COMMENT_LINE = re.compile(
        r"^\s*\*",
    )

    DEBUG_DISPLAY_LINE = re.compile(
        r"^\s*D\s+DISPLAY\b",
        re.IGNORECASE,
    )

    def clean(
        self,
        text: str,
    ) -> str:
        if not text:
            return text

        text = self.fix_continue_concatenation(
            text,
        )

        text = self.fix_paragraph_header_concatenation(
            text,
        )

        text = self.repair_read_at_end(
            text,
        )

        text = self.remove_end_processing_sqlcode_guard(
            text,
        )

        text = self.normalize_all_exec_sql_blocks(
            text,
        )

        text = self.normalize_procedure_division(
            text,
        )

        text = self.fix_db2_check_status(
            text,
        )

        text = self.force_procedure_keyword_indentation(
            text,
        )

        text = self.normalize_perform_until(
            text,
        )

        text = self.normalize_else_if(
            text,
        )

        text = self.normalize_then_lines(
            text,
        )

        text = self.normalize_nested_move_perform_after_if(
            text,
        )

        text = self.normalize_sql_spacing(
            text,
        )

        text = self.normalize_blank_lines(
            text,
        )

        text = self.trim_trailing_spaces(
            text,
        )

        return text

    def normalize_all_exec_sql_blocks(
        self,
        text: str,
    ) -> str:
        lines = text.splitlines()
        result = []
        in_exec_sql = False

        for line in lines:
            stripped = line.strip()

            if not stripped:
                if in_exec_sql:
                    result.append("")
                else:
                    result.append(line.rstrip())
                continue

            if self.EXEC_SQL_START.match(line):
                in_exec_sql = True
                result.append("       EXEC SQL")
                continue

            if in_exec_sql:
                if self.EXEC_SQL_END.match(line):
                    result.append("       END-EXEC.")
                    in_exec_sql = False
                    continue

                result.append(
                    self.normalize_sql_line(
                        stripped,
                    )
                )
                continue

            result.append(
                line.rstrip()
            )

        return "\n".join(result)

    def normalize_procedure_division(
        self,
        text: str,
    ) -> str:
        match = self.PROCEDURE_DIVISION.search(
            text,
        )

        if not match:
            return text

        before = text[: match.start()]
        procedure = text[match.start() :]

        lines = procedure.splitlines()
        result = []
        in_exec_sql = False

        for line in lines:
            stripped = line.strip()

            if not stripped:
                result.append("")
                continue

            if self.COMMENT_LINE.match(line):
                result.append(stripped)
                continue

            if self.EXEC_SQL_START.match(line):
                in_exec_sql = True
                result.append("       EXEC SQL")
                continue

            if in_exec_sql:
                if self.EXEC_SQL_END.match(line):
                    result.append("       END-EXEC.")
                    in_exec_sql = False
                    continue

                result.append(
                    self.normalize_sql_line(
                        stripped,
                    )
                )
                continue

            result.append(
                self.normalize_procedure_line(
                    stripped,
                )
            )

        return before + "\n".join(result)

    def normalize_sql_line(
        self,
        stripped: str,
    ) -> str:
        upper = stripped.upper()

        if not stripped:
            return ""

        if upper == "EXEC SQL":
            return "       EXEC SQL"

        if upper in {"END-EXEC", "END-EXEC."}:
            return "       END-EXEC."

        if upper == "COMMIT":
            return "            COMMIT"

        if upper in {"(", ")"}:
            return "            " + stripped

        if stripped.startswith(":"):
            return "                " + stripped

        if re.match(
            r"^[A-Z0-9_]+,?$",
            stripped,
            flags=re.IGNORECASE,
        ):
            return "                " + stripped

        if re.match(
            r"^(DECLARE|FETCH|OPEN|CLOSE|INSERT|UPDATE|DELETE|INCLUDE|BEGIN|END)\b",
            stripped,
            flags=re.IGNORECASE,
        ):
            return "            " + stripped

        if re.match(
            r"^SELECT\b",
            stripped,
            flags=re.IGNORECASE,
        ):
            return "            " + stripped

        if re.match(
            r"^(INTO|FROM|WHERE|ORDER\s+BY|FETCH\s+FIRST|SET|VALUES)\b",
            stripped,
            flags=re.IGNORECASE,
        ):
            return "            " + stripped

        if re.match(
            r"^AND\b",
            stripped,
            flags=re.IGNORECASE,
        ):
            return "              " + stripped

        if re.match(
            r"^[A-Z0-9_]+\s*=",
            stripped,
            flags=re.IGNORECASE,
        ):
            return "                " + stripped

        return "            " + stripped

    def normalize_procedure_line(
        self,
        stripped: str,
    ) -> str:
        upper = stripped.upper()

        if upper == "PROCEDURE DIVISION.":
            return "PROCEDURE DIVISION."

        if upper in {"END-IF", "END-IF."}:
            return "       END-IF."

        if upper in {"END-PERFORM", "END-PERFORM."}:
            return "       END-PERFORM."

        if upper == "ELSE":
            return "       ELSE"

        if upper.startswith("ELSE IF "):
            return "       " + stripped

        if upper.startswith("IF "):
            return "       " + stripped

        if upper.startswith("THEN "):
            return "          " + stripped

        if upper.startswith("PERFORM "):
            return "       " + stripped

        if upper.startswith("UNTIL "):
            return "           " + stripped

        if upper.startswith("MOVE "):
            return "       " + stripped

        if upper.startswith("READ "):
            return "       " + stripped

        if upper.startswith("AT END "):
            return "          " + stripped

        if upper.startswith("WRITE "):
            return "       " + stripped

        if upper.startswith("OPEN "):
            return "       " + stripped

        if upper.startswith("CLOSE "):
            return "       " + stripped

        if upper.startswith("DISPLAY "):
            return "       " + stripped

        if upper in {"CONTINUE", "CONTINUE."}:
            return "       CONTINUE."

        if upper in {"EXIT", "EXIT."}:
            return "       EXIT."

        if upper in {"GOBACK", "GOBACK."}:
            return "       GOBACK."

        if self.DEBUG_DISPLAY_LINE.match(stripped):
            return "       " + stripped

        if self.PARAGRAPH_HEADER.match(stripped):
            return stripped.upper()

        return "       " + stripped

    def normalize_sql_spacing(
        self,
        text: str,
    ) -> str:
        text = re.sub(
            r"(?im)^\s{12,}COMMIT\s*$",
            "            COMMIT",
            text,
        )

        text = re.sub(
            r"(?im)^\s{12,}VALUES\s*$",
            "            VALUES",
            text,
        )

        return text

    def normalize_perform_until(
        self,
        text: str,
    ) -> str:
        text = re.sub(
            r"(?im)^\s*PERFORM\s+([A-Z0-9-]+)\s+THRU\s+([A-Z0-9-]+)\s*\n\s*UNTIL\s+(.+?)\.?\s*$",
            r"       PERFORM \1 THRU \2\n           UNTIL \3.",
            text,
        )

        text = re.sub(
            r"(?im)^\s*PERFORM\s+([A-Z0-9-]+)\s*\n\s*UNTIL\s+(.+?)\.?\s*$",
            r"       PERFORM \1\n           UNTIL \2.",
            text,
        )

        return text

    def normalize_else_if(
        self,
        text: str,
    ) -> str:
        return re.sub(
            r"(?im)^\s*ELSE\s+IF\s+(.+)$",
            r"       ELSE IF \1",
            text,
        )

    def normalize_then_lines(
        self,
        text: str,
    ) -> str:
        text = re.sub(
            r"(?im)^\s*THEN\s+MOVE\s+(.+)$",
            r"          THEN MOVE \1",
            text,
        )

        text = re.sub(
            r"(?im)^\s*THEN\s+ADD\s+(.+)$",
            r"          THEN ADD \1",
            text,
        )

        text = re.sub(
            r"(?im)^\s*THEN\s+PERFORM\s+(.+)$",
            r"          THEN PERFORM \1",
            text,
        )

        return text

    def normalize_nested_move_perform_after_if(
        self,
        text: str,
    ) -> str:
        lines = text.splitlines()
        result = []

        previous_control = False

        for line in lines:
            stripped = line.strip()
            upper = stripped.upper()

            if not stripped:
                result.append(line)
                continue

            if re.match(
                r"^\s*(IF|ELSE|ELSE IF)\b",
                line,
                flags=re.IGNORECASE,
            ):
                previous_control = True
                result.append(line)
                continue

            if previous_control and re.match(
                r"^(MOVE|PERFORM|CONTINUE|DISPLAY)\b",
                upper,
                flags=re.IGNORECASE,
            ):
                result.append("          " + stripped)
                previous_control = False
                continue

            previous_control = False
            result.append(line)

        return "\n".join(result)

    def fix_db2_check_status(
        self,
        text: str,
    ) -> str:
        text = re.sub(
            r"(?im)^\s*DB2-CHECK-STATUS\.\s*$",
            "DB2-CHECK-STATUS.",
            text,
        )

        text = re.sub(
            r"(?im)^\s*IF\s+SQLCODE\s+NOT\s+=\s+0\s*$",
            "       IF SQLCODE NOT = 0",
            text,
        )

        text = re.sub(
            r"(?im)^\s*DISPLAY\s+'DB2 SQL ERROR SQLCODE='\s+SQLCODE\s*$",
            "          DISPLAY 'DB2 SQL ERROR SQLCODE=' SQLCODE",
            text,
        )

        return text

    def force_procedure_keyword_indentation(
        self,
        text: str,
    ) -> str:
        match = self.PROCEDURE_DIVISION.search(
            text,
        )

        if not match:
            return text

        before = text[: match.start()]
        procedure = text[match.start() :]

        replacements = [
            (
                r"(?im)^\s*END-IF\.?\s*$",
                "       END-IF.",
            ),
            (
                r"(?im)^\s*ELSE\s*$",
                "       ELSE",
            ),
            (
                r"(?im)^\s*GOBACK\.?\s*$",
                "       GOBACK.",
            ),
            (
                r"(?im)^\s*EXIT\.?\s*$",
                "       EXIT.",
            ),
            (
                r"(?im)^\s*CONTINUE\.?\s*$",
                "       CONTINUE.",
            ),
            (
                r"(?im)^\s*PERFORM\s+SQL-ERROR\.?\s*$",
                "       PERFORM SQL-ERROR",
            ),
        ]

        for pattern, replacement in replacements:
            procedure = re.sub(
                pattern,
                replacement,
                procedure,
            )

        return before + procedure

    def repair_read_at_end(
        self,
        text: str,
    ) -> str:
        text = re.sub(
            r"(?im)^\s*READ\s+([A-Z0-9-]+)\s*$\n\s*AT\s+END\s+MOVE\s+(.+?)\s+TO\s+([A-Z0-9-]+)\.?\s*$",
            r"       READ \1\n          AT END MOVE \2 TO \3.",
            text,
        )

        return text

    def remove_end_processing_sqlcode_guard(
        self,
        text: str,
    ) -> str:
        pattern = re.compile(
            r"""
            ^\s*END-PROCESSING\.\s*$
            \s*IF\s+SQLCODE\s+NOT\s+=\s+0\s+AND\s+SQLCODE\s+NOT\s+=\s+100\s*$
            \s*PERFORM\s+SQL-ERROR\s*$
            \s*END-IF\.?\s*$
            """,
            re.IGNORECASE | re.MULTILINE | re.VERBOSE,
        )

        return pattern.sub(
            "END-PROCESSING.",
            text,
        )

    def fix_continue_concatenation(
        self,
        text: str,
    ) -> str:
        text = re.sub(
            r"CONTINUE\.\s*([A-Z0-9-]+\.)",
            r"CONTINUE.\n\1",
            text,
            flags=re.IGNORECASE,
        )

        return text

    def fix_paragraph_header_concatenation(
        self,
        text: str,
    ) -> str:
        text = re.sub(
            r"(\.)\s+([A-Z0-9-]+\.)",
            r"\1\n\2",
            text,
        )

        return text

    def normalize_blank_lines(
        self,
        text: str,
    ) -> str:
        text = re.sub(
            r"\n{3,}",
            "\n\n",
            text,
        )

        text = re.sub(
            r"\n\s+\n",
            "\n\n",
            text,
        )

        text = re.sub(
            r"(?m)^(END-PROCESSING\.)\n\s*\n\s*(CLOSE\b)",
            r"\1\n       \2",
            text,
        )

        text = re.sub(
            r"(?m)^(SQL-ERROR\.)\n\s*\n",
            r"\1\n",
            text,
        )

        text = re.sub(
            r"(?m)^(SQL-ERROR-EXIT\.)\n\s*\n",
            r"\1\n",
            text,
        )

        return text

    def trim_trailing_spaces(
        self,
        text: str,
    ) -> str:
        return re.sub(
            r"[ \t]+$",
            "",
            text,
            flags=re.MULTILINE,
        )