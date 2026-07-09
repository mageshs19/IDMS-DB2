from idms_modernizer.domain.db2_models import (
    DB2Model,
    DB2Table,
    DB2Column,
)
from idms_modernizer.domain.schema_models import (
    SchemaMetadata,
)
from idms_modernizer.services.name_normalizer import (
    NameNormalizer,
)


class ExcelSheetMappingService:
    """
    Builds the Excel Sheet Mapping table as rows.

    Columns not available from schema-only input are intentionally left empty.
    """

    COLUMNS = [
        "Cobol Record IDMS",
        "Cobol Zone",
        "IDMS Key",
        "IDMS PIC Clause",
        "Length of Field Bytes",
        "Field end position",
        "DB2 Key",
        "New DB2 Record",
        "New DB2_Field_name",
        "New DB2 Data Type",
        "Hopex Expression TypeRemark",
        "Relation",
        "Reference Field Name (CopyBook)",
        "Reference Field PIC Clause",
        "Cross Application DB2 Field Name",
        "Cross Appln DB2 Data Type",
        "Basetype",
    ]

    def build(
        self,
        metadata: SchemaMetadata,
        db2_model: DB2Model,
    ) -> list[dict[str, str]]:
        table_lookup = self.build_table_lookup(
            db2_model,
        )

        relationship_lookup = self.build_relationship_lookup(
            metadata,
        )

        rows: list[dict[str, str]] = []

        for record in metadata.records:
            record_name = NameNormalizer.normalize(
                record.name,
            )

            table = table_lookup.get(record_name)

            column_lookup = (
                self.build_column_lookup(table)
                if table is not None
                else {}
            )

            for field in record.fields:
                field_name = NameNormalizer.normalize(
                    field.name,
                )

                db2_column = self.find_matching_column(
                    field_name=field_name,
                    column_lookup=column_lookup,
                )

                row = self.empty_row()

                row["Cobol Record IDMS"] = record.name or ""
                row["Cobol Zone"] = record.cobol_zone or ""
                row["IDMS Key"] = record.primary_key or ""
                row["IDMS PIC Clause"] = field.picture or ""
                row["Length of Field Bytes"] = (
                    str(field.length)
                    if field.length is not None
                    else ""
                )
                row["Field end position"] = (
                    str(field.end_position)
                    if field.end_position is not None
                    else ""
                )

                if table is not None:
                    row["New DB2 Record"] = table.name or ""

                if db2_column is not None:
                    row["New DB2_Field_name"] = db2_column.name or ""
                    row["New DB2 Data Type"] = db2_column.datatype or ""
                    row["DB2 Key"] = self.db2_key_label(
                        table=table,
                        column=db2_column,
                    )

                row["Relation"] = relationship_lookup.get(
                    record_name,
                    "",
                )

                row["Basetype"] = field.basetype or ""

                rows.append(row)

        return rows

    def empty_row(
        self,
    ) -> dict[str, str]:
        return {
            column: ""
            for column in self.COLUMNS
        }

    def build_table_lookup(
        self,
        db2_model: DB2Model,
    ) -> dict[str, DB2Table]:
        lookup: dict[str, DB2Table] = {}

        for table in db2_model.tables:
            lookup[
                NameNormalizer.normalize(table.name)
            ] = table

        return lookup

    def build_column_lookup(
        self,
        table: DB2Table,
    ) -> dict[str, DB2Column]:
        lookup: dict[str, DB2Column] = {}

        for column in table.columns:
            lookup[
                NameNormalizer.normalize(column.name)
            ] = column

            lookup[
                self.remove_record_suffix(
                    NameNormalizer.normalize(column.name)
                )
            ] = column

        return lookup

    def find_matching_column(
        self,
        field_name: str,
        column_lookup: dict[str, DB2Column],
    ) -> DB2Column | None:
        if field_name in column_lookup:
            return column_lookup[field_name]

        suffix_removed = self.remove_record_suffix(
            field_name,
        )

        return column_lookup.get(
            suffix_removed,
        )

    def build_relationship_lookup(
        self,
        metadata: SchemaMetadata,
    ) -> dict[str, str]:
        lookup: dict[str, list[str]] = {}

        for relationship in metadata.relationships:
            owner = NameNormalizer.normalize(
                relationship.owner_record,
            )

            member = NameNormalizer.normalize(
                relationship.member_record,
            )

            set_name = relationship.set_name or ""

            lookup.setdefault(
                owner,
                [],
            ).append(
                f"OWNER:{set_name}->{relationship.member_record}"
            )

            lookup.setdefault(
                member,
                [],
            ).append(
                f"MEMBER:{set_name}<-{relationship.owner_record}"
            )

        return {
            record_name: "; ".join(values)
            for record_name, values in lookup.items()
        }

    def db2_key_label(
        self,
        table: DB2Table | None,
        column: DB2Column,
    ) -> str:
        labels: list[str] = []

        if column.primary_key:
            labels.append("PK")

        if table is not None:
            for foreign_key in table.foreign_keys:
                if foreign_key.column_name == column.name:
                    labels.append("FK")
                    break

        return "/".join(labels)

    def remove_record_suffix(
        self,
        name: str,
    ) -> str:
        normalized = NameNormalizer.normalize(
            name,
        )

        parts = normalized.split("_")

        if (
            len(parts) > 1
            and parts[-1].isdigit()
            and len(parts[-1]) == 4
        ):
            return "_".join(parts[:-1])

        return normalized