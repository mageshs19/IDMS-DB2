from idms_modernizer.domain.canonical_models import CanonicalSchema
from idms_modernizer.domain.db2_models import DB2Model
from idms_modernizer.services.db2_mapping_service import DB2MappingService


class DB2ModelBuilder:

    def __init__(self):
        self.mapping_service = DB2MappingService()

    def build(
        self,
        schema: CanonicalSchema
    ) -> DB2Model:

        return self.mapping_service.build_db2_model(
            schema
        )