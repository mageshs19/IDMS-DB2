from pydantic import BaseModel


class SetMembership(BaseModel):

    set_name: str

    role: str


class Relationship(BaseModel):

    set_name: str

    owner_record: str

    member_record: str

    cardinality: str = "1:N"