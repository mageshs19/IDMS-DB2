import re


class OutputValidator:
    """
    Validates generated DB2 COBOL output.

    This validator is generic:
    - No application record names are hard-coded.
    - No demo set names are hard-coded.
    - Paragraph names like READY-AREA are not treated as IDMS READY commands.
    - Multiline SQL column lists are not falsely flagged as empty parentheses.
    """

    FORBIDDEN_EXECUTABLE_PATTERNS = [
        r"^\s*OBTAIN\b",
        r"^\s*FIND\b",
        r"^\s*READY(?:\s|\.|$)",
        r"^\s*BIND(?:\s|\.|$)",
        r"^\s*FINISH\.?\s*$",
        r"^\s*KEEP\b",
        r"^\s*STORE\b",
        r"^\s*MODIFY\b",
        r"^\s*ERASE\b",
        r"^\s*CONNECT\b",
        r"^\s*DISCONNECT\b",
        r"^\s*GET\b",
        r"^\s*IF\s+DB-[A-Z0-9-]+\b",
        r"^\s*PERFORM\s+IDMS-STATUS\.?\s*$",
        r"^\s*USAGE-MODE\s+IS\s+UPDATE\.?\s*$",
    ]

    REQUIRED = [
        "EXEC SQL",
        "SQLCA",
        "END-EXEC",
    ]

    EXEC_SQL_START = re.compile(
        r"^\s*EXEC\s+SQL\b",
        re.IGNORECASE,
    )

    EXEC_SQL_END = re.compile(
        r"^\s*END-EXEC\.?\s*$",
        re.IGNORECASE,
    )

    COMMENT_LINE = re.compile(
        r"^\s*\*",
    )

    PARAGRAPH_HEADER_PATTERN = re.compile(
        r"^\s*[A-Z0-9-]+\.\s*$",
        re.IGNORECASE,
    )

    UNCONVERTED_IDMS_FIELD_PATTERN = re.compile(
        r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d{4}\b",
        re.IGNORECASE,
    )

    HOST_VARIABLE_PATTERN = re.compile(
        r"\b(?:HV|NI)-[A-Z0-9-]+(?:$\d+:\d+$)?\b",
        re.IGNORECASE,
    )

    def validate(
        self,
        text: str,
    ) -> list[str]:
        errors: list[str] = []

        executable_text = self.executable_text(
            text,
        )

        upper_executable = executable_text.upper()
        upper_all = text.upper()

        self.validate_forbidden_idms_patterns(
            upper=upper_executable,
            errors=errors,
        )

        self.validate_required_db2_tokens(
            upper=upper_all,
            errors=errors,
        )

        self.validate_no_nested_host_variables(
            upper=upper_all,
            errors=errors,
        )

        self.validate_no_rewritten_report_fields(
            upper=upper_all,
            errors=errors,
        )

        self.validate_no_unconverted_idms_schema_fields(
            text=executable_text,
            errors=errors,
        )

        self.validate_sql_blocks_closed(
            text=text,
            errors=errors,
        )

        self.validate_sql_punctuation(
            text=text,
            errors=errors,
        )

        return errors

    def executable_text(
        self,
        text: str,
    ) -> str:
        lines: list[str] = []
        in_exec_sql = False
        in_data_division = False
        in_procedure_division = False

        for line in text.splitlines():
            stripped = line.strip()
            upper = stripped.upper()

            if not stripped:
                continue

            if self.COMMENT_LINE.match(line):
                continue

            if upper.startswith("DATA DIVISION"):
                in_data_division = True
                in_procedure_division = False
                continue

            if upper.startswith("PROCEDURE DIVISION"):
                in_data_division = False
                in_procedure_division = True
                lines.append(line)
                continue

            if self.EXEC_SQL_START.match(line):
                in_exec_sql = True
                lines.append(line)

                if self.EXEC_SQL_END.match(line):
                    in_exec_sql = False

                continue

            if in_exec_sql:
                lines.append(line)

                if self.EXEC_SQL_END.match(line):
                    in_exec_sql = False

                continue

            if in_data_division:
                continue

            if not in_procedure_division:
                continue

            lines.append(line)

        return "\n".join(lines)

    def validate_forbidden_idms_patterns(
        self,
        upper: str,
        errors: list[str],
    ) -> None:
        for pattern in self.FORBIDDEN_EXECUTABLE_PATTERNS:
            if re.search(
                pattern,
                upper,
                flags=re.IGNORECASE | re.MULTILINE,
            ):
                errors.append(
                    f"Forbidden IDMS executable pattern remains: {pattern}"
                )

    def validate_required_db2_tokens(
        self,
        upper: str,
        errors: list[str],
    ) -> None:
        for token in self.REQUIRED:
            if token not in upper:
                errors.append(
                    f"Required DB2 token missing: {token}"
                )

    def validate_no_nested_host_variables(
        self,
        upper: str,
        errors: list[str],
    ) -> None:
        if re.search(
            r"\bHV-[A-Z0-9-]+-HV-[A-Z0-9-]+\b",
            upper,
        ):
            errors.append(
                "Converted output contains nested host variables like HV-...-HV-...."
            )

        if re.search(
            r"\bNI-[A-Z0-9-]+-NI-[A-Z0-9-]+\b",
            upper,
        ):
            errors.append(
                "Converted output contains nested null indicators like NI-...-NI-...."
            )

    def validate_no_rewritten_report_fields(
        self,
        upper: str,
        errors: list[str],
    ) -> None:
        bad_patterns = [
            r"\bHV-[A-Z0-9-]+-IN\b",
            r"\bHV-[A-Z0-9-]+-OUT\b",
            r"\bNI-[A-Z0-9-]+-IN\b",
            r"\bNI-[A-Z0-9-]+-OUT\b",
        ]

        for pattern in bad_patterns:
            if re.search(
                pattern,
                upper,
            ):
                errors.append(
                    "Converted output appears to have rewritten input/output report fields."
                )
                return

    def validate_no_unconverted_idms_schema_fields(
        self,
        text: str,
        errors: list[str],
    ) -> None:
        lines = text.splitlines()
        in_exec_sql = False

        for line in lines:
            if self.EXEC_SQL_START.match(line):
                in_exec_sql = True

                if self.EXEC_SQL_END.match(line):
                    in_exec_sql = False

                continue

            if in_exec_sql:
                if self.EXEC_SQL_END.match(line):
                    in_exec_sql = False

                continue

            if self.COMMENT_LINE.match(line):
                continue

            if self.PARAGRAPH_HEADER_PATTERN.match(line):
                continue

            scrubbed = self.remove_host_variables(
                line,
            )

            matches = self.UNCONVERTED_IDMS_FIELD_PATTERN.findall(
                scrubbed,
            )

            for match in matches:
                upper_match = match.upper()

                if upper_match.startswith("HV-"):
                    continue

                if upper_match.startswith("NI-"):
                    continue

                errors.append(
                    f"Unconverted IDMS schema field remains in procedure logic: {match}"
                )

    def remove_host_variables(
        self,
        line: str,
    ) -> str:
        return self.HOST_VARIABLE_PATTERN.sub(
            "",
            line,
        )

    def validate_sql_blocks_closed(
        self,
        text: str,
        errors: list[str],
    ) -> None:
        start_count = 0
        end_count = 0

        for line in text.splitlines():
            if self.EXEC_SQL_START.match(line):
                start_count += 1

            if self.EXEC_SQL_END.match(line):
                end_count += 1

        if start_count != end_count:
            errors.append(
                f"EXEC SQL / END-EXEC block mismatch: EXEC SQL={start_count}, END-EXEC={end_count}"
            )

    def validate_sql_punctuation(
        self,
        text: str,
        errors: list[str],
    ) -> None:
        sql_blocks = self.extract_sql_blocks(
            text,
        )

        for block in sql_blocks:
            self.validate_sql_commas(
                block=block,
                errors=errors,
            )

    def extract_sql_blocks(
        self,
        text: str,
    ) -> list[str]:
        blocks: list[str] = []
        current: list[str] = []
        in_exec_sql = False

        for line in text.splitlines():
            if self.EXEC_SQL_START.match(line):
                in_exec_sql = True
                current = [
                    line,
                ]

                if self.EXEC_SQL_END.match(line):
                    blocks.append(
                        "\n".join(current),
                    )

                    current = []
                    in_exec_sql = False

                continue

            if in_exec_sql:
                current.append(
                    line,
                )

                if self.EXEC_SQL_END.match(line):
                    blocks.append(
                        "\n".join(current),
                    )

                    current = []
                    in_exec_sql = False

        return blocks

    def validate_sql_commas(
        self,
        block: str,
        errors: list[str],
    ) -> None:
        if re.search(
            r",\s*,",
            block,
        ):
            errors.append(
                "SQL block contains duplicate commas."
            )

        if re.search(
            r",\s*(FROM|WHERE|END-EXEC)",
            block,
            flags=re.IGNORECASE,
        ):
            errors.append(
                "SQL block contains trailing comma before FROM, WHERE, or END-EXEC."
            )