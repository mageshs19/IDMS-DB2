from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class CobolNode(Protocol):

    def render(
        self,
        indent: int = 7,
        final: bool = False
    ) -> list[str]:
        ...


def pad(
    indent: int
) -> str:

    return " " * indent


def ensure_period(
    value: str
) -> str:

    value = value.rstrip()

    if value.endswith("."):
        return value

    return value + "."


@dataclass
class PreRenderedBlock:

    lines: list[str]

    def render(
        self,
        indent: int = 7,
        final: bool = False
    ) -> list[str]:

        result = list(
            self.lines
        )

        if final and result:
            result[-1] = ensure_period(
                result[-1]
            )

        return result


@dataclass
class RawLines:

    lines: list[str]

    def render(
        self,
        indent: int = 7,
        final: bool = False
    ) -> list[str]:

        result: list[str] = []

        for line in self.lines:
            if line.strip():
                result.append(
                    pad(indent) + line.strip()
                )
            else:
                result.append("")

        if final and result:
            result[-1] = ensure_period(
                result[-1]
            )

        return result


@dataclass
class Move:

    source: str
    target: str

    def render(
        self,
        indent: int = 7,
        final: bool = False
    ) -> list[str]:

        return [
            f"{pad(indent)}MOVE {self.source} TO {self.target}."
        ]


@dataclass
class Perform:

    paragraph: str

    def render(
        self,
        indent: int = 7,
        final: bool = False
    ) -> list[str]:

        return [
            f"{pad(indent)}PERFORM {self.paragraph}."
        ]


@dataclass
class Continue:

    def render(
        self,
        indent: int = 7,
        final: bool = False
    ) -> list[str]:

        return [
            f"{pad(indent)}CONTINUE."
        ]


@dataclass
class ReadAtEndMove:

    file_name: str
    source: str
    target: str

    def render(
        self,
        indent: int = 7,
        final: bool = False
    ) -> list[str]:

        source = self.source

        if (
            len(source) == 1
            and not source.startswith("'")
            and not source.endswith("'")
        ):
            source = f"'{source}'"

        return [
            f"{pad(indent)}READ {self.file_name} AT END MOVE {source} TO {self.target}."
        ]


@dataclass
class Write:

    record: str
    source: str | None = None

    def render(
        self,
        indent: int = 7,
        final: bool = False
    ) -> list[str]:

        if self.source:
            return [
                f"{pad(indent)}WRITE {self.record} FROM {self.source}."
            ]

        return [
            f"{pad(indent)}WRITE {self.record}."
        ]


@dataclass
class ExecSql:

    sql: str

    def render(
        self,
        indent: int = 7,
        final: bool = False
    ) -> list[str]:

        normalized_lines = self._normalize_sql_lines(
            self.sql
        )

        result: list[str] = []

        for line in normalized_lines:
            if line.strip():
                result.append(
                    pad(indent) + line.rstrip()
                )
            else:
                result.append("")

        if final and result:
            result[-1] = ensure_period(
                result[-1]
            )

        return result

    def _normalize_sql_lines(
        self,
        sql: str
    ) -> list[str]:

        raw_lines = sql.splitlines()

        stripped_lines = [
            line.rstrip()
            for line in raw_lines
            if line.strip()
        ]

        if not stripped_lines:
            return []

        min_indent = min(
            len(line) - len(line.lstrip(" "))
            for line in stripped_lines
        )

        normalized: list[str] = []

        for line in raw_lines:
            if line.strip():
                normalized.append(
                    line[min_indent:].rstrip()
                )
            else:
                normalized.append("")

        return normalized


@dataclass
class IfBlock:

    condition: str
    then_body: list[CobolNode] = field(
        default_factory=list
    )
    else_body: list[CobolNode] = field(
        default_factory=list
    )

    def render(
        self,
        indent: int = 7,
        final: bool = False
    ) -> list[str]:

        result: list[str] = [
            f"{pad(indent)}IF {self.condition}"
        ]

        result.extend(
            render_nodes(
                self.then_body,
                indent + 3
            )
        )

        if self.else_body:
            result.append(
                f"{pad(indent)}ELSE"
            )

            result.extend(
                render_nodes(
                    self.else_body,
                    indent + 3
                )
            )

        terminator = "END-IF."

        if not final:
            terminator = "END-IF"

        result.append(
            f"{pad(indent)}{terminator}"
        )

        return result

    def with_prefix(
        self,
        prefix: CobolNode
    ) -> PrefixedBlock:

        return PrefixedBlock(
            prefix=prefix,
            block=self
        )


@dataclass
class PrefixedBlock:

    prefix: CobolNode
    block: CobolNode

    def render(
        self,
        indent: int = 7,
        final: bool = False
    ) -> list[str]:

        result: list[str] = []

        result.extend(
            self.prefix.render(
                indent=indent
            )
        )

        result.append("")

        result.extend(
            self.block.render(
                indent=indent,
                final=final
            )
        )

        return result


@dataclass
class PerformUntil:

    condition: str
    body: list[CobolNode] = field(
        default_factory=list
    )

    def render(
        self,
        indent: int = 7,
        final: bool = False
    ) -> list[str]:

        result: list[str] = [
            f"{pad(indent)}PERFORM UNTIL {self.condition}"
        ]

        result.extend(
            render_nodes(
                self.body,
                indent + 3
            )
        )

        terminator = "END-PERFORM."

        if not final:
            terminator = "END-PERFORM"

        result.append(
            f"{pad(indent)}{terminator}"
        )

        return result


@dataclass
class Paragraph:

    name: str
    body: list[CobolNode] = field(
        default_factory=list
    )

    def render(
        self,
        indent: int = 7,
        final: bool = False
    ) -> list[str]:

        result: list[str] = [
            f"{self.name}."
        ]

        if self.body:
            result.extend(
                render_nodes(
                    self.body,
                    indent,
                    terminate_last=True
                )
            )

        return result


def render_nodes(
    nodes: list[CobolNode],
    indent: int = 7,
    terminate_last: bool = False
) -> list[str]:

    result: list[str] = []

    for index, node in enumerate(nodes):
        is_last = (
            terminate_last
            and index == len(nodes) - 1
        )

        result.extend(
            node.render(
                indent=indent,
                final=is_last
            )
        )

    return result


def render_paragraph(
    name: str,
    nodes: list[CobolNode]
) -> str:

    paragraph = Paragraph(
        name=name,
        body=nodes
    )

    return "\n".join(
        paragraph.render()
    )