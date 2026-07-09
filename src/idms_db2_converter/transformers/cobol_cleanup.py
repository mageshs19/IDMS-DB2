import re


class CobolCleanup:
    """
    Final cleanup pass for generated COBOL.

    Goals:
    - Preserve EXEC SQL blocks.
    - Normalize PROCEDURE DIVISION formatting.
    - Fix END-IF, ELSE, CONTINUE, EXIT, GOBACK indentation.
    - Fix SQL indentation for common SQL clauses.
    - Fix READ ... AT END indentation.
    - Fix paragraph header concatenation.
    - Avoid changing DATA DIVISION and WORKING-STORAGE declarations.
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

        text = self.normalize_procedure_division(
            text,
        )

        text = self.fix_db2_check_status(
            text,
        )

        text = self.force_procedure_keyword_indentation(
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

    def normalize_procedure_division(
        self,
        text: str,
    ) -> str:
        match = self.PROCEDURE_DIVISION.search(
            text,
        )

        if not match:
            return text

        before = text[:match.start()]
        procedure = text[match.start():]

        procedure = self.normalize_lines(
            procedure,
        )

        return before + procedure

    def normalize_lines(
        self,
        text: str,
    ) -> str:
        lines = text.splitlines()
        output: list[str] = []

        in_exec_sql = False

        for line in lines:
            stripped = line.strip()

            if not stripped:
                output.append("")
                continue

            if self.EXEC_SQL_START.match(line):
                in_exec_sql = True
                output.append(
                    "       EXEC SQL",
                )
                continue

            if in_exec_sql:
                output.append(
                    self.normalize_exec_sql_line(
                        stripped,
                    )
                )

                if self.EXEC_SQL_END.match(line):
                    in_exec_sql = False

                continue

            if self.COMMENT_LINE.match(line):
                output.append(line)
                continue

            if self.DEBUG_DISPLAY_LINE.match(line):
                output.append(stripped)
                continue

            if self.PARAGRAPH_HEADER.match(line):
                output.append(stripped)
                continue

            output.append(
                self.normalize_procedure_line(
                    stripped,
                )
            )

        return "\n".join(output)

    def normalize_exec_sql_line(
        self,
        stripped: str,
    ) -> str:
        upper = stripped.upper()

        if upper == "EXEC SQL":
            return "       EXEC SQL"

        if upper in {
            "END-EXEC",
            "END-EXEC.",
        }:
            return "       END-EXEC."

        if upper == "COMMIT":
            return "            COMMIT"

        if upper in {
            "(",
            ")",
        }:
            return "               " + stripped

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
            return "                " + stripped

        if re.match(
            r"^(INTO|FROM|WHERE|ORDER\s+BY|FETCH\s+FIRST|SET|VALUES)\b",
            stripped,
            flags=re.IGNORECASE,
        ):
            return "            " + stripped

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

        if upper in {
            "END-IF",
            "END-IF.",
        }:
            return "       END-IF."

        if upper in {
            "END-PERFORM",
            "END-PERFORM.",
        }:
            return "       END-PERFORM"

        if upper == "ELSE":
            return "       ELSE"

        if upper in {
            "CONTINUE",
            "CONTINUE.",
        }:
            return "       CONTINUE."

        if upper in {
            "EXIT",
            "EXIT.",
        }:
            return "       EXIT."

        if upper in {
            "GOBACK",
            "GOBACK.",
        }:
            return "       GOBACK."

        if upper == "THEN":
            return "       THEN"

        if upper.startswith("THEN "):
            return "       " + stripped

        if upper.startswith("AT END "):
            return "          " + stripped

        if upper.startswith("DISPLAY "):
            return "          " + stripped

        if self.is_common_procedure_statement(
            upper,
        ):
            return "       " + stripped

        return stripped

    def is_common_procedure_statement(
        self,
        upper: str,
    ) -> bool:
        prefixes = (
            "IF ",
            "MOVE ",
            "PERFORM ",
            "READ ",
            "WRITE ",
            "OPEN ",
            "CLOSE ",
            "ADD ",
            "SUBTRACT ",
            "MULTIPLY ",
            "DIVIDE ",
            "COMPUTE ",
            "GO TO ",
            "SET ",
            "CALL ",
            "EVALUATE ",
            "WHEN ",
            "END-EVALUATE",
            "PERFORM UNTIL ",
        )

        return upper.startswith(prefixes)

    def fix_db2_check_status(
        self,
        text: str,
    ) -> str:
        pattern = re.compile(
            r"""
            ^\s*DB2-CHECK-STATUS\.\s*
            \n\s*IF\s+SQLCODE\s+NOT\s*=\s*0\s*
            \n\s*DISPLAY\s+'DB2\s+SQL\s+ERROR\s+SQLCODE='\s+SQLCODE\s*
            \n\s*END-IF\.?
            """,
            re.IGNORECASE | re.MULTILINE | re.VERBOSE,
        )

        replacement = "\n".join(
            [
                "DB2-CHECK-STATUS.",
                "       IF SQLCODE NOT = 0",
                "          DISPLAY 'DB2 SQL ERROR SQLCODE=' SQLCODE",
                "       END-IF.",
            ]
        )

        return pattern.sub(
            replacement,
            text,
        )

    def repair_read_at_end(
        self,
        text: str,
    ) -> str:
        lines = text.splitlines()
        output: list[str] = []

        in_exec_sql = False

        for line in lines:
            stripped = line.strip()

            if self.EXEC_SQL_START.match(line):
                in_exec_sql = True
                output.append(line)
                continue

            if in_exec_sql:
                output.append(line)

                if self.EXEC_SQL_END.match(line):
                    in_exec_sql = False

                continue

            if re.match(
                r"^AT\s+END\b",
                stripped,
                flags=re.IGNORECASE,
            ):
                output.append(
                    "          " + stripped,
                )
                continue

            output.append(line)

        return "\n".join(output)

    def remove_end_processing_sqlcode_guard(
        self,
        text: str,
    ) -> str:
        pattern = re.compile(
            r"""
            (\n\s*END-PROCESSING\.\s*)
            \n\s*IF\s+SQLCODE\s+NOT\s*=\s*0\s*
            \n\s*PERFORM\s+SQL-ERROR\.?\s*
            \n\s*END-IF\.?
            """,
            re.IGNORECASE | re.MULTILINE | re.VERBOSE,
        )

        return pattern.sub(
            r"\1",
            text,
        )

    def fix_paragraph_header_concatenation(
        self,
        text: str,
    ) -> str:
        replacements = [
            r"EXEC\s+SQL",
            r"IF\s+",
            r"MOVE\s+",
            r"PERFORM\s+",
            r"CONTINUE\.?",
            r"DISPLAY\s+",
            r"READ\s+",
            r"WRITE\s+",
            r"OPEN\s+",
            r"CLOSE\s+",
        ]

        for statement in replacements:
            text = re.sub(
                rf"(\b[A-Z0-9-]+\.)\s*({statement})",
                r"\1\n       \2",
                text,
                flags=re.IGNORECASE,
            )

        return text

    def fix_continue_concatenation(
        self,
        text: str,
    ) -> str:
        text = re.sub(
            r"CONTINUE\.\s*PERFORM\s+IDMS-STATUS\.?",
            "CONTINUE.",
            text,
            flags=re.IGNORECASE,
        )

        text = re.sub(
            r"CONTINUE\.([A-Z0-9-]+\.)",
            r"CONTINUE.\n\1",
            text,
            flags=re.IGNORECASE,
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

        before = text[:match.start()]
        procedure = text[match.start():]

        procedure = re.sub(
            r"(?im)^\s*END-IF\.?\s*$",
            "       END-IF.",
            procedure,
        )

        procedure = re.sub(
            r"(?im)^\s*CONTINUE\.?\s*$",
            "       CONTINUE.",
            procedure,
        )

        procedure = re.sub(
            r"(?im)^\s*ELSE\s*$",
            "       ELSE",
            procedure,
        )

        procedure = re.sub(
            r"(?im)^\s*GOBACK\.?\s*$",
            "       GOBACK.",
            procedure,
        )

        procedure = re.sub(
            r"(?im)^\s*EXIT\.?\s*$",
            "       EXIT.",
            procedure,
        )

        procedure = re.sub(
            r"(?im)^\s*DISPLAY\s+'DB2 SQL ERROR SQLCODE='\s+SQLCODE\s*$",
            "          DISPLAY 'DB2 SQL ERROR SQLCODE=' SQLCODE",
            procedure,
        )

        procedure = re.sub(
            r"(?im)^\s*PERFORM\s+SQL-ERROR\.?\s*$",
            "          PERFORM SQL-ERROR",
            procedure,
        )

        return before + procedure

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