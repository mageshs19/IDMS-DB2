from pydantic import BaseModel, Field


class DocumentLine(BaseModel):
    line_number: int
    text: str


class DocumentPage(BaseModel):
    page_number: int
    lines: list[DocumentLine] = Field(
        default_factory=list
    )


class DocumentModel(BaseModel):
    pages: list[DocumentPage] = Field(
        default_factory=list
    )