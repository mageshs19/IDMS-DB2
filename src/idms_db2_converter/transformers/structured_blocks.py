class StructuredBlocks:
    @staticmethod
    def indent(block: str, spaces: int) -> str:
        pad = " " * spaces
        lines = []

        for line in block.splitlines():
            stripped = line.strip()
            if stripped:
                lines.append(pad + stripped)
            else:
                lines.append("")

        return "\n".join(lines)

    @staticmethod
    def sqlcode_select_block(
        sql: str,
        not_found_body: str,
        success_body: str,
        indent: int = 7,
    ) -> str:
        pad = " " * indent
        inner = " " * (indent + 3)
        inner2 = " " * (indent + 6)

        return "\n".join(
            [
                StructuredBlocks.indent(sql, indent),
                "",
                f"{pad}IF SQLCODE = 100",
                StructuredBlocks.indent(not_found_body, indent + 3),
                f"{pad}ELSE",
                f"{inner}IF SQLCODE NOT = 0",
                f"{inner2}PERFORM SQL-ERROR",
                f"{inner}ELSE",
                StructuredBlocks.indent(success_body, indent + 6),
                f"{inner}END-IF",
                f"{pad}END-IF.",
            ]
        )

    @staticmethod
    def select_first_then_owner_chain(
        first_select_sql: str,
        owner_select_sql: str,
        first_not_found_body: str,
        owner_not_found_body: str,
        success_body: str,
        indent: int = 7,
    ) -> str:
        pad = " " * indent
        inner = " " * (indent + 3)
        inner2 = " " * (indent + 6)
        inner3 = " " * (indent + 9)

        return "\n".join(
            [
                StructuredBlocks.indent(first_select_sql, indent),
                "",
                f"{pad}IF SQLCODE = 100",
                StructuredBlocks.indent(first_not_found_body, indent + 3),
                f"{pad}ELSE",
                f"{inner}IF SQLCODE NOT = 0",
                f"{inner2}PERFORM SQL-ERROR",
                f"{inner}ELSE",
                StructuredBlocks.indent(owner_select_sql, indent + 6),
                "",
                f"{inner2}IF SQLCODE = 100",
                StructuredBlocks.indent(owner_not_found_body, indent + 9),
                f"{inner2}ELSE",
                f"{inner3}IF SQLCODE NOT = 0",
                f"{inner3}   PERFORM SQL-ERROR",
                f"{inner3}ELSE",
                StructuredBlocks.indent(success_body, indent + 12),
                f"{inner3}END-IF",
                f"{inner2}END-IF",
                f"{inner}END-IF",
                f"{pad}END-IF.",
            ]
        )

    @staticmethod
    def nullable_owner_block(
        null_indicator: str,
        null_body: str,
        owner_select_sql: str,
        success_body: str,
        fallback_body: str,
        indent: int = 7,
    ) -> str:
        pad = " " * indent
        inner = " " * (indent + 3)

        return "\n".join(
            [
                f"{pad}IF {null_indicator} < 0",
                StructuredBlocks.indent(null_body, indent + 3),
                f"{pad}ELSE",
                StructuredBlocks.indent(owner_select_sql, indent + 3),
                "",
                f"{inner}IF SQLCODE = 0",
                StructuredBlocks.indent(success_body, indent + 6),
                f"{inner}ELSE",
                StructuredBlocks.indent(fallback_body, indent + 6),
                f"{inner}END-IF",
                f"{pad}END-IF.",
            ]
        )

    @staticmethod
    def owner_select_block(
        owner_select_sql: str,
        success_body: str,
        fallback_body: str,
        indent: int = 7,
    ) -> str:
        pad = " " * indent
        inner = " " * (indent + 3)

        return "\n".join(
            [
                StructuredBlocks.indent(owner_select_sql, indent),
                "",
                f"{pad}IF SQLCODE = 0",
                StructuredBlocks.indent(success_body, indent + 3),
                f"{pad}ELSE",
                StructuredBlocks.indent(fallback_body, indent + 3),
                f"{pad}END-IF.",
            ]
        )

    @staticmethod
    def cursor_loop_block(
        cursor_name: str,
        fetch_paragraph: str,
        empty_body: str,
        before_loop_body: str,
        walk_paragraph: str,
        walk_exit: str,
        indent: int = 7,
    ) -> str:
        pad = " " * indent
        inner = " " * (indent + 3)
        inner2 = " " * (indent + 6)

        return "\n".join(
            [
                f"{pad}EXEC SQL",
                f"{pad}     OPEN {cursor_name}",
                f"{pad}END-EXEC.",
                "",
                f"{pad}IF SQLCODE NOT = 0",
                f"{inner}PERFORM SQL-ERROR",
                f"{pad}ELSE",
                f"{inner}PERFORM {fetch_paragraph}",
                "",
                f"{inner}IF SQLCODE = 100",
                StructuredBlocks.indent(empty_body, indent + 6),
                f"{inner}ELSE",
                StructuredBlocks.indent(before_loop_body, indent + 6),
                "",
                f"{inner2}PERFORM UNTIL SQLCODE = 100",
                f"{inner2}   PERFORM {walk_paragraph} THRU {walk_exit}",
                f"{inner2}   PERFORM {fetch_paragraph}",
                f"{inner2}END-PERFORM",
                f"{inner}END-IF",
                "",
                f"{inner}EXEC SQL",
                f"{inner}     CLOSE {cursor_name}",
                f"{inner}END-EXEC",
                f"{pad}END-IF",
            ]
        )