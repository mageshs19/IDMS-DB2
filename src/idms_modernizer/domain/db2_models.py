from dataclasses import (
    dataclass,
    field
)


@dataclass
class DB2Column:

    name: str

    datatype: str

    nullable: bool = True

    primary_key: bool = False


@dataclass
class DB2ForeignKey:

    column_name: str

    reference_table: str

    reference_column: str


@dataclass
class DB2Table:

    name: str

    columns: list[DB2Column] = field(
        default_factory=list
    )

    foreign_keys: list[
        DB2ForeignKey
    ] = field(
        default_factory=list
    )

    primary_key: str | None = None


@dataclass
class DB2Model:

    tables: list[DB2Table] = field(
        default_factory=list
    )