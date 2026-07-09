from pydantic import BaseModel

from idms_modernizer.domain.db2_models import Table
from idms_modernizer.domain.relationship_models import (
    Relationship
)
from idms_modernizer.domain.schema_models import (
    SchemaMetadata
)


class ConversionContext(
    BaseModel
):

    schema_metadata: (
        SchemaMetadata | None
    ) = None

    relationships: (
        list[Relationship]
    ) = []

    db2_tables: (
        list[Table]
    ) = []