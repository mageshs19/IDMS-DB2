import re

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

    Fixes included:
    - Cobol Zone now shows COBOL field mapping value instead of region.
      Example: 02 SELECTION-DATE-0400
    - YEAR / MONTH / DAY date child fields are mapped to consolidated DB2 DATE column.
      Example: SELECTION-YEAR-0400 maps to SELECTION_DATE_0400.
    - New DB2_Field_name and New DB2 Data Type are populated for date child rows.
    - New DB2 Record remains populated from the matched DB2 table.
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

    DATE_PART_NAMES = {
        "YEAR",
        "MONTH",
        "DAY",
        "YR",
        "MO",
        "DY",
    }

    DATE_PART_TO_DATE = {
        "YEAR": "DATE",
        "MONTH": "DATE",
        "DAY": "DATE",
        "YR": "DATE",
        "MO": "DATE",
        "DY": "DATE",
    }

    def build(
        self,
        metadata: SchemaMetadata,
        db2_model: DB2Model,
    ) -> list[dict[str, str]]:
        table_lookup = self.build_table_lookup(
            db2_model=db2_model,
        )

        relationship_lookup = self.build_relationship_lookup(
            metadata=metadata,
        )

        rows: list[dict[str, str]] = []

        for record in metadata.records:
            record_name = NameNormalizer.normalize(
                record.name,
            )

            table = table_lookup.get(
                record_name,
            )

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

                row["Cobol Zone"] = self.build_cobol_zone_value(
                    record=record,
                    field=field,
                    db2_column=db2_column,
                )

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
            normalized_table_name = NameNormalizer.normalize(
                table.name,
            )

            lookup[normalized_table_name] = table

        return lookup

    def build_column_lookup(
        self,
        table: DB2Table,
    ) -> dict[str, DB2Column]:
        lookup: dict[str, DB2Column] = {}

        for column in table.columns:
            normalized_column_name = NameNormalizer.normalize(
                column.name,
            )

            lookup[normalized_column_name] = column

            suffix_removed_name = self.remove_record_suffix(
                normalized_column_name,
            )

            lookup[suffix_removed_name] = column

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

        if suffix_removed in column_lookup:
            return column_lookup[suffix_removed]

        date_column_name = self.date_part_to_date_column_name(
            field_name,
        )

        if date_column_name:
            if date_column_name in column_lookup:
                return column_lookup[date_column_name]

            date_suffix_removed = self.remove_record_suffix(
                date_column_name,
            )

            if date_suffix_removed in column_lookup:
                return column_lookup[date_suffix_removed]

        return None

    def build_cobol_zone_value(
        self,
        record,
        field,
        db2_column: DB2Column | None,
    ) -> str:
        field_name = field.name or ""

        if not field_name:
            return record.cobol_zone or ""

        normalized_field_name = NameNormalizer.normalize(
            field_name,
        )

        if db2_column is not None:
            normalized_db2_column = NameNormalizer.normalize(
                db2_column.name,
            )

            if (
                self.is_date_part_name(normalized_field_name)
                and self.is_date_column_name(normalized_db2_column)
            ):
                cobol_date_name = self.date_part_to_cobol_date_name(
                    field_name,
                )

                return self.format_cobol_level_and_name(
                    level=2,
                    name=cobol_date_name,
                )

        field_level = getattr(
            field,
            "level",
            None,
        )

        if field_level is not None:
            return self.format_cobol_level_and_name(
                level=field_level,
                name=field_name,
            )

        return field_name or record.cobol_zone or ""

    def format_cobol_level_and_name(
        self,
        level: int | str | None,
        name: str,
    ) -> str:
        if level is None:
            return name or ""

        try:
            level_value = int(level)
            return f"{level_value:02d} {name}".strip()
        except Exception:
            return f"{level} {name}".strip()

    def date_part_to_date_column_name(
        self,
        field_name: str,
    ) -> str | None:
        normalized = NameNormalizer.normalize(
            field_name,
        )

        tokens = self.split_name_tokens(
            normalized,
        )

        if len(tokens) < 2:
            return None

        changed = False
        output_tokens: list[str] = []

        for token in tokens:
            upper_token = token.upper()

            if upper_token in self.DATE_PART_TO_DATE:
                output_tokens.append(
                    self.DATE_PART_TO_DATE[upper_token],
                )
                changed = True
            else:
                output_tokens.append(
                    upper_token,
                )

        if not changed:
            return None

        return "_".join(output_tokens)

    def date_part_to_cobol_date_name(
        self,
        field_name: str,
    ) -> str:
        tokens = self.split_name_tokens(
            field_name,
        )

        if len(tokens) < 2:
            return field_name

        output_tokens: list[str] = []
        changed = False

        for token in tokens:
            upper_token = token.upper()

            if upper_token in self.DATE_PART_TO_DATE:
                output_tokens.append("DATE")
                changed = True
            else:
                output_tokens.append(upper_token)

        if not changed:
            return field_name

        return "-".join(output_tokens)

    def is_date_part_name(
        self,
        field_name: str,
    ) -> bool:
        tokens = self.split_name_tokens(
            field_name,
        )

        for token in tokens:
            if token.upper() in self.DATE_PART_NAMES:
                return True

        return False

    def is_date_column_name(
        self,
        column_name: str,
    ) -> bool:
        tokens = self.split_name_tokens(
            column_name,
        )

        for token in tokens:
            if token.upper() == "DATE":
                return True

        return False

    def split_name_tokens(
        self,
        name: str,
    ) -> list[str]:
        return [
            token
            for token in re.split(r"[-_\s]+", name or "")
            if token
        ]

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

        tokens = self.split_name_tokens(
            normalized,
        )

        if (
            len(tokens) > 1
            and tokens[-1].isdigit()
            and len(tokens[-1]) == 4
        ):
            return "_".join(tokens[:-1])

        return "_".join(tokens)