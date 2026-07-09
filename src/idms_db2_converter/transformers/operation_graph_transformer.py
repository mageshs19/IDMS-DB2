import re

from idms_db2_converter.generators.cobol_builder import (
    Continue,
    ExecSql,
    IfBlock,
    Move,
    Perform,
    PerformUntil,
    PreRenderedBlock,
    ReadAtEndMove,
    Write,
    render_nodes,
    render_paragraph,
)
from idms_db2_converter.generators.fetch_paragraphs import FetchParagraphGenerator
from idms_db2_converter.generators.naming import Naming
from idms_db2_converter.generators.sql_snippets import SqlSnippets
from idms_db2_converter.models import SchemaModel
from idms_db2_converter.transformers.metadata_helpers import MetadataHelpers


class OperationGraphTransformer:
    def __init__(self, schema: SchemaModel):
        self.schema = schema
        self.sql = SqlSnippets(schema)
        self.meta = MetadataHelpers(schema)
        self.fetch_generator = FetchParagraphGenerator(schema)
        self.used_cursor_sets: set[str] = set()

    def has_graph(self) -> bool:
        return bool(self.schema.paragraph_operation_graph)

    def transform(self, text: str) -> str:
        for paragraph_name, operations in self.schema.paragraph_operation_graph.items():
            rendered = self._render_paragraph(paragraph_name, operations)
            text = self._replace_paragraph(text, paragraph_name, rendered)

        return text

    def _replace_paragraph(self, text: str, paragraph_name: str, replacement: str) -> str:
        pattern = re.compile(
            rf"^\s*{re.escape(paragraph_name)}\.\s*\n.*?(?=^\s*[A-Z0-9-]+\.\s*$)",
            re.IGNORECASE | re.MULTILINE | re.DOTALL,
        )

        if pattern.search(text):
            return pattern.sub(replacement + "\n", text, count=1)

        return text + "\n" + replacement + "\n"

    def _render_paragraph(self, paragraph_name: str, operations: list[dict]) -> str:
        nodes = self._render_operations(operations)
        return render_paragraph(paragraph_name, nodes)

    def _render_operations(self, operations: list[dict]) -> list:
        nodes = []

        for operation in operations:
            op_type = operation.get("type", "").upper()

            if op_type == "MOVE":
                nodes.append(
                    Move(
                        source=self.meta.map_source(operation["from"]),
                        target=operation["to"],
                    )
                )

            elif op_type == "MOVE_DATE_PART":
                nodes.append(
                    Move(
                        source=self.meta.map_source(operation["from"]),
                        target=operation["to"],
                    )
                )

            elif op_type == "PERFORM":
                nodes.append(Perform(paragraph=operation["paragraph"]))

            elif op_type == "WRITE":
                nodes.append(
                    Write(
                        record=operation["record"],
                        source=operation.get("source"),
                    )
                )

            elif op_type == "READ_NEXT_INPUT":
                at_end_move = operation.get("at_end_move", {})
                nodes.append(
                    ReadAtEndMove(
                        file_name=operation["file"],
                        source=at_end_move.get("from", "Y"),
                        target=at_end_move.get("to", "EOF-SW"),
                    )
                )

            elif op_type == "CONTINUE":
                nodes.append(Continue())

            elif op_type == "OBTAIN_CALC":
                nodes.append(self._node_obtain_calc(operation))

            elif op_type == "CURSOR_LOOP":
                nodes.append(self._node_cursor_loop(operation))

            elif op_type == "FIRST_MEMBER_TO_OWNER_LOOKUP":
                nodes.extend(self._nodes_first_member_to_owner_lookup(operation))

            elif op_type == "OWNER_LOOKUP":
                nodes.extend(self._nodes_owner_lookup(operation))

        return nodes

    def _node_obtain_calc(self, operation: dict):
        record = operation["record"].upper()
        select_sql = self.sql.select_for_record_by_pk(record)

        not_found_nodes = self._render_operations(operation.get("not_found", []))
        success_nodes = self._render_operations(operation.get("success", []))

        lines = []
        lines.extend(ExecSql(select_sql).render(indent=7))
        lines.append("")
        lines.extend(
            IfBlock(
                condition="SQLCODE = 100",
                then_body=not_found_nodes,
                else_body=[
                    IfBlock(
                        condition="SQLCODE NOT = 0",
                        then_body=[Perform("SQL-ERROR")],
                        else_body=success_nodes,
                    )
                ],
            ).render(indent=7, final=True)
        )

        return PreRenderedBlock(lines)

    def _node_cursor_loop(self, operation: dict):
        set_name = operation["set"].upper()
        self.used_cursor_sets.add(set_name)

        cursor_name = Naming.cursor(set_name)
        fetch_paragraph = self.fetch_generator.paragraph_name(set_name)

        process_paragraph = operation["process_paragraph"]
        exit_paragraph = operation.get("exit_paragraph")
        empty_nodes = self._render_operations(operation.get("empty", []))
        before_loop_nodes = self._render_operations(operation.get("before_loop", []))

        perform_target = process_paragraph
        if exit_paragraph:
            perform_target = f"{process_paragraph} THRU {exit_paragraph}"

        cursor_open = ExecSql(
            "\n".join(
                [
                    "EXEC SQL",
                    f"     OPEN {cursor_name}",
                    "END-EXEC.",
                ]
            )
        )

        cursor_close = ExecSql(
            "\n".join(
                [
                    "EXEC SQL",
                    f"     CLOSE {cursor_name}",
                    "END-EXEC.",
                ]
            )
        )

        loop_nodes = before_loop_nodes + [
            PerformUntil(
                condition="SQLCODE = 100",
                body=[
                    Perform(perform_target),
                    Perform(fetch_paragraph),
                ],
            )
        ]

        return IfBlock(
            condition="SQLCODE NOT = 0",
            then_body=[Perform("SQL-ERROR")],
            else_body=[
                Perform(fetch_paragraph),
                IfBlock(
                    condition="SQLCODE = 100",
                    then_body=empty_nodes,
                    else_body=loop_nodes,
                ),
                cursor_close,
            ],
        ).with_prefix(cursor_open)

    def _nodes_first_member_to_owner_lookup(self, operation: dict) -> list:
        lookup_name = operation.get("name")
        first_member_set = operation["first_member_set"].upper()
        owner_set = operation["owner_set"].upper()

        lookup = self.meta.lookup_by_name(lookup_name) if lookup_name else None
        if not lookup:
            lookup = self.meta.lookup_by_first_member_set(first_member_set)

        not_found_moves = lookup.get("not_found_moves", []) if lookup else []
        success_moves = lookup.get("success_moves", []) if lookup else []

        first_select = ExecSql(self.sql.select_first_child_for_set(first_member_set))
        owner_select = ExecSql(self.sql.select_for_owner(owner_set))

        not_found_nodes = self.meta.moves_to_nodes(not_found_moves)
        owner_not_found_nodes = self.meta.moves_to_nodes(not_found_moves)
        success_nodes = self.meta.moves_to_nodes(success_moves) or [Continue()]

        return [
            first_select,
            IfBlock(
                condition="SQLCODE = 100",
                then_body=not_found_nodes,
                else_body=[
                    IfBlock(
                        condition="SQLCODE NOT = 0",
                        then_body=[Perform("SQL-ERROR")],
                        else_body=[
                            owner_select,
                            IfBlock(
                                condition="SQLCODE = 100",
                                then_body=owner_not_found_nodes,
                                else_body=[
                                    IfBlock(
                                        condition="SQLCODE NOT = 0",
                                        then_body=[Perform("SQL-ERROR")],
                                        else_body=success_nodes,
                                    )
                                ],
                            ),
                        ],
                    )
                ],
            ),
        ]

    def _nodes_owner_lookup(self, operation: dict) -> list:
        lookup_name = operation.get("name")
        owner_set = operation["owner_set"].upper()

        lookup = self.meta.lookup_by_name(lookup_name) if lookup_name else None
        if not lookup:
            lookup = self.meta.lookup_by_owner_set(owner_set)

        not_found_moves = lookup.get("not_found_moves", []) if lookup else []
        success_moves = lookup.get("success_moves", []) if lookup else []

        not_found_nodes = self.meta.moves_to_nodes(not_found_moves)
        success_nodes = self.meta.moves_to_nodes(success_moves) or [Continue()]
        owner_select = ExecSql(self.sql.select_for_owner(owner_set))

        nullable_meta = self.schema.nullable_fk_map.get(owner_set)
        null_indicator = nullable_meta.get("null_indicator") if nullable_meta else None

        if null_indicator:
            return [
                IfBlock(
                    condition=f"{null_indicator} < 0",
                    then_body=not_found_nodes,
                    else_body=[
                        owner_select,
                        IfBlock(
                            condition="SQLCODE = 0",
                            then_body=success_nodes,
                            else_body=[
                                IfBlock(
                                    condition="SQLCODE = 100",
                                    then_body=not_found_nodes,
                                    else_body=[Perform("SQL-ERROR")],
                                )
                            ],
                        ),
                    ],
                )
            ]

        return [
            owner_select,
            IfBlock(
                condition="SQLCODE = 0",
                then_body=success_nodes,
                else_body=[
                    IfBlock(
                        condition="SQLCODE = 100",
                        then_body=not_found_nodes,
                        else_body=[Perform("SQL-ERROR")],
                    )
                ],
            ),
        ]