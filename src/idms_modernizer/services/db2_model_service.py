from idms_modernizer.domain.db2_models import (
    DB2Column,
    DB2Model,
    DB2Table
)


class DB2ModelService:

    def build(
        self,
        metadata
    ) -> DB2Model:

        tables = []

        for record in metadata.records:

            columns = []

            for field in record.fields:

                columns.append(
                    DB2Column(
                        name=field.name,
                        datatype="VARCHAR(255)"
                    )
                )

            tables.append(
                DB2Table(
                    name=record.name,
                    columns=columns,
                    foreign_keys=[]
                )
            )

        return DB2Model(
            tables=tables
        )