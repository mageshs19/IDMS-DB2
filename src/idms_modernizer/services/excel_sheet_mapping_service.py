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

    Behavior:
    - Cobol Zone shows the original COBOL field with level number.
      Example: 03 SELECTION-YEAR-0400

    - YEAR / MONTH / DAY date child fields are mapped to consolidated DB2
      DATE columns.
      Example: SELECTION-YEAR-0400 maps to SELECTION_DATE_0400.

    - IDMS Key shows only corresponding IDMS key labels:
      CALC appears only on the field matching record.primary_key.
      SET appears only on the field mapped to a DB2 FK column.

    - DB2 Key shows PK, FK, or PK/FK based on DB2Table.primary_key,
      DB2Column.primary_key, and DB2Table.foreign_keys.

    Generic behavior only:
    - No hardcoded record names.
    - No hardcoded business field names.
    - No application-specific suffix map.
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
        "New DB2 Field_name",
        "New DB2 Data Type",
        "Hopex Expression TypeRemark",
        "Relation",
        "Reference Field Name (CopyBook) ",
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
                self.build_column_lookup(
                    table=table,
                )
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

                row["IDMS Key"] = self.idms_key_label(
                    record=record,
                    field=field,
                    table=table,
                    db2_column=db2_column,
                )

                row["IDMS PIC Clause"] = self.get_field_picture(
                    field=field,
                )

                row["Length of Field Bytes"] = self.to_string(
                    self.get_field_length(
                        field=field,
                    )
                )

                row["Field end position"] = self.to_string(
                    self.get_field_end_position(
                        field=field,
                    )
                )

                row["DB2 Key"] = self.db2_key_label(
                    table=table,
                    column=db2_column,
                )

                row["New DB2 Record"] = (
                    table.name
                    if table is not None and getattr(table, "name", None)
                    else ""
                )

                row["New DB2 Field_name"] = (
                    db2_column.name
                    if db2_column is not None and getattr(db2_column, "name", None)
                    else ""
                )

                row["New DB2 Data Type"] = self.get_db2_datatype(
                    db2_column=db2_column,
                )

                row["Hopex Expression TypeRemark"] = ""

                row["Relation"] = relationship_lookup.get(
                    record_name,
                    "",
                )

                row["Reference Field Name (CopyBook) "] = ""
                row["Reference Field PIC Clause"] = ""
                row["Cross Application DB2 Field Name"] = ""
                row["Cross Appln DB2 Data Type"] = ""

                row["Basetype"] = self.get_field_basetype(
                    field=field,
                )

                rows.append(
                    row,
                )

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

        if db2_model is None:
            return lookup

        for table in getattr(db2_model, "tables", []) or []:
            normalized_table_name = NameNormalizer.normalize(
                table.name,
            )

            if normalized_table_name:
                lookup[normalized_table_name] = table

            suffix_removed_table_name = self.remove_record_suffix(
                normalized_table_name,
            )

            if suffix_removed_table_name:
                lookup[suffix_removed_table_name] = table

        return lookup

    def build_column_lookup(
        self,
        table: DB2Table,
    ) -> dict[str, DB2Column]:
        lookup: dict[str, DB2Column] = {}

        for column in getattr(table, "columns", []) or []:
            normalized_column_name = NameNormalizer.normalize(
                column.name,
            )

            if normalized_column_name:
                lookup[normalized_column_name] = column

            suffix_removed_name = self.remove_record_suffix(
                normalized_column_name,
            )

            if suffix_removed_name:
                lookup[suffix_removed_name] = column

        return lookup

    def build_relationship_lookup(
        self,
        metadata: SchemaMetadata,
    ) -> dict[str, str]:
        lookup: dict[str, str] = {}

        for record in getattr(metadata, "records", []) or []:
            record_name = NameNormalizer.normalize(
                getattr(record, "name", None),
            )

            if not record_name:
                continue

            relation_parts: list[str] = []

            for membership in getattr(record, "set_memberships", []) or []:
                relation_text = self.build_membership_relation_text(
                    membership=membership,
                )

                if relation_text:
                    relation_parts.append(
                        relation_text,
                    )

            if relation_parts:
                lookup[record_name] = "; ".join(
                    relation_parts,
                )

        return lookup

    def build_membership_relation_text(
        self,
        membership,
    ) -> str:
        relation_type = (
            getattr(membership, "relation_type", None)
            or getattr(membership, "role", None)
            or getattr(membership, "type", None)
            or ""
        )

        set_name = (
            getattr(membership, "set_name", None)
            or getattr(membership, "name", None)
            or ""
        )

        owner_record = (
            getattr(membership, "owner_record", None)
            or getattr(membership, "owner", None)
            or ""
        )

        member_record = (
            getattr(membership, "member_record", None)
            or getattr(membership, "member", None)
            or ""
        )

        relation_type = str(relation_type).upper()
        set_name = str(set_name)
        owner_record = str(owner_record)
        member_record = str(member_record)

        if not set_name:
            return ""

        if relation_type == "OWNER":
            if member_record:
                return f"OWNER: {set_name} -> {member_record}"

            return f"OWNER: {set_name}"

        if relation_type == "MEMBER":
            if owner_record:
                return f"MEMBER: {set_name} <- {owner_record}"

            return f"MEMBER: {set_name}"

        if owner_record and member_record:
            return f"{relation_type}: {set_name}: {owner_record} -> {member_record}".strip(
                ": "
            )

        if owner_record:
            return f"{relation_type}: {set_name} <- {owner_record}".strip(
                ": "
            )

        if member_record:
            return f"{relation_type}: {set_name} -> {member_record}".strip(
                ": "
            )

        return f"{relation_type}: {set_name}".strip(
            ": "
        )

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
        """
        Builds the Cobol Zone value for the Excel sheet.

        Important:
        This preserves the original COBOL field name.

        Example:
        03 SELECTION-YEAR-0400 stays as 03 SELECTION-YEAR-0400.

        DATE consolidation is only used for matching the DB2 column.
        """

        field_name = getattr(
            field,
            "name",
            "",
        ) or ""

        if not field_name:
            return getattr(
                record,
                "cobol_zone",
                "",
            ) or ""

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

        return field_name

    def idms_key_label(
        self,
        record,
        field,
        table: DB2Table | None,
        db2_column: DB2Column | None,
    ) -> str:
        """
        Returns CALC, SET, or CALC; SET for the IDMS Key column.

        CALC:
        - Only when the current COBOL field matches record.primary_key.

        SET:
        - Only when the current mapped DB2 column is an FK column.
        - This prevents SET from appearing on every field in a record.
        """

        labels: list[str] = []

        if self.is_calc_key_field(
            record=record,
            field=field,
        ):
            labels.append(
                "CALC",
            )

        if self.is_set_key_field(
            table=table,
            db2_column=db2_column,
        ):
            labels.append(
                "SET",
            )

        return "; ".join(
            labels,
        )

    def is_calc_key_field(
        self,
        record,
        field,
    ) -> bool:
        primary_key = getattr(
            record,
            "primary_key",
            None,
        )

        field_name = getattr(
            field,
            "name",
            None,
        )

        if not primary_key or not field_name:
            return False

        return self.same_column_name(
            left=primary_key,
            right=field_name,
        )

    def is_set_key_field(
        self,
        table: DB2Table | None,
        db2_column: DB2Column | None,
    ) -> bool:
        if table is None or db2_column is None:
            return False

        return self.is_foreign_key_column(
            table=table,
            column=db2_column,
        )

    def db2_key_label(
        self,
        table: DB2Table | None,
        column: DB2Column | None,
    ) -> str:
        if table is None or column is None:
            return ""

        labels: list[str] = []

        if self.is_primary_key_column(
            table=table,
            column=column,
        ):
            labels.append(
                "PK",
            )

        if self.is_foreign_key_column(
            table=table,
            column=column,
        ):
            labels.append(
                "FK",
            )

        return "/".join(
            labels,
        )

    def is_primary_key_column(
        self,
        table: DB2Table,
        column: DB2Column,
    ) -> bool:
        if getattr(
            column,
            "primary_key",
            False,
        ):
            return True

        table_primary_key = getattr(
            table,
            "primary_key",
            None,
        )

        if not table_primary_key:
            return False

        return self.same_column_name(
            left=table_primary_key,
            right=column.name,
        )

    def is_foreign_key_column(
        self,
        table: DB2Table,
        column: DB2Column,
    ) -> bool:
        for foreign_key in getattr(table, "foreign_keys", []) or []:
            foreign_key_column_name = getattr(
                foreign_key,
                "column_name",
                None,
            )

            if self.same_column_name(
                left=foreign_key_column_name,
                right=column.name,
            ):
                return True

        return False

    def same_column_name(
        self,
        left: str | None,
        right: str | None,
    ) -> bool:
        if not left or not right:
            return False

        normalized_left = NameNormalizer.normalize(
            left,
        )

        normalized_right = NameNormalizer.normalize(
            right,
        )

        if normalized_left == normalized_right:
            return True

        return self.remove_record_suffix(
            normalized_left,
        ) == self.remove_record_suffix(
            normalized_right,
        )

    def format_cobol_level_and_name(
        self,
        level: int | str | None,
        name: str,
    ) -> str:
        if level is None:
            return name or ""

        try:
            level_value = int(
                level,
            )

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

        return " ".join(
            output_tokens,
        )

    def date_part_to_cobol_date_name(
        self,
        field_name: str,
    ) -> str:
        """
        Kept only for compatibility with any existing callers.

        This method converts YEAR / MONTH / DAY to DATE, but it is not used
        for the Cobol Zone column because Cobol Zone must preserve the
        original COBOL field.
        """

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
                output_tokens.append(
                    "DATE",
                )

                changed = True

            else:
                output_tokens.append(
                    upper_token,
                )

        if not changed:
            return field_name

        return "-".join(
            output_tokens,
        )

    def is_date_part_name(
        self,
        field_name: str,
    ) -> bool:
        tokens = self.split_name_tokens(
            field_name,
        )

        return any(
            token.upper() in self.DATE_PART_NAMES
            for token in tokens
        )

    def is_date_column_name(
        self,
        column_name: str,
    ) -> bool:
        tokens = self.split_name_tokens(
            column_name,
        )

        return any(
            token.upper() == "DATE"
            for token in tokens
        )

    def split_name_tokens(
        self,
        value: str,
    ) -> list[str]:
        normalized = NameNormalizer.normalize(
            value,
        )

        return [
            token
            for token in re.split(
                r"[\s_-]+",
                normalized,
            )
            if token
        ]

    def remove_record_suffix(
        self,
        value: str,
    ) -> str:
        normalized = NameNormalizer.normalize(
            value,
        )

        tokens = self.split_name_tokens(
            normalized,
        )

        if (
            len(tokens) > 1
            and tokens[-1].isdigit()
            and len(tokens[-1]) == 4
        ):
            return " ".join(
                tokens[:-1],
            )

        return normalized

    def get_field_picture(
        self,
        field,
    ) -> str:
        return (
            getattr(field, "picture", None)
            or getattr(field, "pic_clause", None)
            or getattr(field, "pic", None)
            or ""
        )

    def get_field_length(
        self,
        field,
    ):
        return (
            getattr(field, "length", None)
            or getattr(field, "byte_length", None)
            or getattr(field, "field_length", None)
            or ""
        )

    def get_field_end_position(
        self,
        field,
    ):
        return (
            getattr(field, "end_position", None)
            or getattr(field, "field_end_position", None)
            or getattr(field, "end", None)
            or ""
        )

    def get_field_basetype(
        self,
        field,
    ) -> str:
        basetype = (
            getattr(field, "basetype", None)
            or getattr(field, "base_type", None)
            or ""
        )

        if basetype:
            return str(
                basetype,
            )

        picture = self.get_field_picture(
            field=field,
        )

        picture_upper = str(
            picture,
        ).upper()

        if "X" in picture_upper:
            return "TEXT"

        if "9" in picture_upper or "V" in picture_upper:
            return "NUMERIC"

        return ""

    def get_db2_datatype(
        self,
        db2_column: DB2Column | None,
    ) -> str:
        if db2_column is None:
            return ""

        datatype = (
            getattr(db2_column, "datatype", None)
            or getattr(db2_column, "data_type", None)
            or getattr(db2_column, "type", None)
            or ""
        )

        return str(
            datatype,
        )

    def to_string(
        self,
        value,
    ) -> str:
        if value is None:
            return ""

        return str(
            value,
        )