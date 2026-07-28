from dataclasses import dataclass, field


@dataclass
class DB2Column:
    name: str
    datatype: str
    nullable: bool = True
    primary_key: bool = False
    generated: bool = False
    source_kind: str = ""


@dataclass
class DB2ForeignKey:
    column_name: str
    reference_table: str
    reference_column: str
    set_name: str = ""


@dataclass
class DB2Table:
    name: str
    columns: list[DB2Column] = field(default_factory=list)
    foreign_keys: list[DB2ForeignKey] = field(default_factory=list)
    primary_key: str | None = None
    primary_keys: list[str] = field(default_factory=list)


@dataclass
class DB2Model:
    tables: list[DB2Table] = field(default_factory=list)