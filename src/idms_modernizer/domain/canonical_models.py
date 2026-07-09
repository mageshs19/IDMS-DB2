from pydantic import BaseModel, Field


class CanonicalField(BaseModel):

    name: str

    datatype: str | None = None

    length: int | None = None

    scale: int | None = None

    occurs: bool = False

    occurs_max: int | None = None


class CanonicalRecord(BaseModel):

    name: str

    primary_key: str | None = None

    record_id: str | None = None

    location_mode: str | None = None

    fields: list["CanonicalField"] = Field(
        default_factory=list
    )


class CanonicalSet(BaseModel):

    name: str

    owner_record: str | None = None

    member_record: str | None = None

    order_mode: str | None = None


class CanonicalRelationship(BaseModel):

    set_name: str

    parent_record: str

    child_record: str

    cardinality: str = "1:N"


class CanonicalSchema(BaseModel):

    records: list[CanonicalRecord] = Field(
        default_factory=list
    )

    sets: list[CanonicalSet] = Field(
        default_factory=list
    )

    relationships: list[
        CanonicalRelationship
    ] = Field(
        default_factory=list
    )