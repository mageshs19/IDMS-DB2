from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Column:
    name: str
    datatype: str
    length: Optional[int] = None
    scale: Optional[int] = None
    nullable: bool = True


@dataclass
class Record:
    name: str
    primary_key: Optional[str]
    fields: Dict[str, Column] = field(default_factory=dict)


@dataclass
class Relationship:
    set_name: str
    parent_record: str
    child_record: str
    cardinality: Optional[str] = None
    parent_key: Optional[str] = None
    child_fk: Optional[str] = None
    order_by: List[str] = field(default_factory=list)


@dataclass
class SchemaModel:
    records: Dict[str, Record] = field(default_factory=dict)
    relationships: Dict[str, Relationship] = field(default_factory=dict)
    field_map: Dict[str, dict] = field(default_factory=dict)

    record_table_map: Dict[str, str] = field(default_factory=dict)
    calc_key_map: Dict[str, dict] = field(default_factory=dict)
    set_ordering_map: Dict[str, dict] = field(default_factory=dict)
    navigation_intent: Dict[str, dict] = field(default_factory=dict)
    nullable_fk_map: Dict[str, dict] = field(default_factory=dict)
    date_part_map: Dict[str, dict] = field(default_factory=dict)
    output_semantics: Dict[str, dict] = field(default_factory=dict)
    paragraph_operation_graph: Dict[str, list] = field(default_factory=dict)
    validation_messages: List[str] = field(default_factory=list)
    schema_source: Optional[str] = None

    def has_schema_objects(self) -> bool:
        return bool(self.records or self.relationships)


    def is_empty(self) -> bool:
        return not self.has_schema_objects()


    def add_validation_message(self, message: str) -> None:
        if not hasattr(self, "validation_messages"):
            self.validation_messages = []

        self.validation_messages.append(message)


@dataclass
class CobolAnalysis:
    program_id: Optional[str] = None
    idms_records: List[str] = field(default_factory=list)
    obtain_calc_records: List[str] = field(default_factory=list)
    obtain_next: List[tuple[str, str]] = field(default_factory=list)
    obtain_owner_sets: List[str] = field(default_factory=list)
    find_first_sets: List[str] = field(default_factory=list)

    store_records: List[str] = field(default_factory=list)
    modify_records: List[str] = field(default_factory=list)
    erase_records: List[str] = field(default_factory=list)
    ready_update_areas: List[str] = field(default_factory=list)

    field_references: List[str] = field(default_factory=list)
    idms_fields: List[str] = field(default_factory=list)



@dataclass
class Paragraph:
    name: str
    text: str