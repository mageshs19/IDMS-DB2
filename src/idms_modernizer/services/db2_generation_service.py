from idms_modernizer.generators.ddl_generator import (
    DDLGenerator
)

from idms_modernizer.services.db2_mapping_service import (
    DB2MappingService
)


class DB2GenerationService:

    def __init__(self):

        self.mapper = (
            DB2MappingService()
        )

        self.ddl_generator = (
            DDLGenerator()
        )

    def generate(
        self,
        canonical_schema
    ):

        db2_model = (
            self.mapper.build_db2_model(
                canonical_schema
            )
        )

        ddl = (
            self.ddl_generator.generate(
                db2_model
            )
        )

        return db2_model, ddl