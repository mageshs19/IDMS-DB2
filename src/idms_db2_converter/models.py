from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Column:
    name: str
    datatype: str
    length: Optional[int] = None
    scale: Optional[int] = None
    nullable: bool = True
    primary_key: bool = False
    generated: bool = False
    source_kind: str = ""


@dataclass
class Record:
    name: str
    primary_key: Optional[str] = None
    fields: Dict[str, Column] = field(default_factory=dict)

    # New composite PK support.
    # Existing code can continue using primary_key.
    primary_keys: List[str] = field(default_factory=list)

    def effective_primary_keys(self) -> List[str]:
        keys: List[str] = []

        if self.primary_keys:
            keys.extend(self.primary_keys)

        if self.primary_key and self.primary_key not in keys:
            keys.append(self.primary_key)

        return keys

    def set_primary_keys(self, keys: List[str]) -> None:
        cleaned: List[str] = []

        for key in keys or []:
            if not key:
                continue

            normalized = str(key).upper()

            if normalized in cleaned:
                continue

            cleaned.append(normalized)

        self.primary_keys = cleaned
        self.primary_key = cleaned[0] if cleaned else None

        for key in cleaned:
            if key in self.fields:
                self.fields[key].primary_key = True
                self.fields[key].nullable = False


@dataclass
class Relationship:
    set_name: str
    parent_record: str
    child_record: str
    cardinality: Optional[str] = None

    # Backward-compatible single key fields.
    parent_key: Optional[str] = None
    child_fk: Optional[str] = None

    # New composite relationship support.
    parent_keys: List[str] = field(default_factory=list)
    child_fks: List[str] = field(default_factory=list)

    order_by: List[str] = field(default_factory=list)

    def effective_parent_keys(self) -> List[str]:
        keys: List[str] = []

        if self.parent_keys:
            keys.extend(self.parent_keys)

        if self.parent_key and self.parent_key not in keys:
            keys.append(self.parent_key)

        return keys

    def effective_child_fks(self) -> List[str]:
        keys: List[str] = []

        if self.child_fks:
            keys.extend(self.child_fks)

        if self.child_fk and self.child_fk not in keys:
            keys.append(self.child_fk)

        return keys


@dataclass
class SchemaModel:
    records: Dict[str, Record] = field(default_factory=dict)
    relationships: Dict[str, Relationship] = field(default_factory=dict)

    field_map: Dict[str, dict] = field(default_factory=dict)
    record_table_map: Dict[str, str] = field(default_factory=dict)
    calc_key_map: Dict[str, dict] = field(default_factory=dict)

    # Existing Phase 2 metadata maps.
    set_ordering_map: Dict[str, dict] = field(default_factory=dict)
    navigation_intent: Dict[str, dict] = field(default_factory=dict)
    nullable_fk_map: Dict[str, dict] = field(default_factory=dict)
    date_part_map: Dict[str, dict] = field(default_factory=dict)
    output_semantics: Dict[str, dict] = field(default_factory=dict)
    paragraph_operation_graph: Dict[str, list] = field(default_factory=dict)
    validation_messages: List[str] = field(default_factory=list)

    # New key metadata from Phase 1.
    table_key_map: Dict[str, dict] = field(default_factory=dict)

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