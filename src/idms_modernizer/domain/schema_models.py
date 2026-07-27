from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from idms_modernizer.domain.relationship_models import (
    Relationship,
    SetMembership,
)


class DataField(BaseModel):
    name: str
    level: int | None = None

    datatype: str | None = None
    length: int | None = None
    scale: int | None = None
    picture: str | None = None

    start_position: int | None = None
    end_position: int | None = None
    basetype: str | None = None

    has_child: bool = False
    is_group: bool = False

    occurs: bool = False
    occurs_min: int | None = None
    occurs_max: int | None = None

    raw_line: str | None = None
    rest: str | None = None


@dataclass
class Record:
    name: str

    # Physical / DDL-safe fields.
    # Used by canonical schema, DB2 model, DDL, Phase 2 metadata, and COBOL conversion.
    fields: list[DataField] = field(
        default_factory=list,
    )

    # Excel-only complete field list.
    # Includes group fields, leaf fields, outer date groups, key groups, attributes, OCCURS groups.
    mapping_fields: list[DataField] = field(
        default_factory=list,
    )

    set_memberships: list[SetMembership] = field(
        default_factory=list,
    )

    primary_key: str | None = None
    cobol_zone: str | None = None


class SetDefinition(BaseModel):
    name: str
    owner_record: str | None = None
    member_record: str | None = None


class SchemaMetadata(BaseModel):
    records: list[Record] = Field(
        default_factory=list,
    )

    sets: list[SetDefinition] = Field(
        default_factory=list,
    )

    relationships: list[Relationship] = Field(
        default_factory=list,
    )