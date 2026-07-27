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

    Final behavior:
    - Cobol Zone preserves original COBOL field with level number.
    - All existing metadata fields are shown in the sheet.
    - CALC appears only when current field matches record.primary_key.
    - SET appears only when DB2 Key contains FK.
    - No synthetic FK rows are added.
    - No fallback SET is assigned to first row of a table.
    - Inner date parts are shown as COBOL fields, but DB2 mapping columns
      are kept blank.
    - Inferred outer DATE rows are added for complete date groups.
    - Supports client-side date part variants:
      YEAR / MONTH / DAY
      YR / MO / DY
      Y / M / D
      YY / MM / DD
      YYYY / MM / DD
      DY / DM / DD
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

    YEAR_PARTS = {
        "YEAR",
        "YR",
        "Y",
        "YY",
        "YYYY",
    }

    MONTH_PARTS = {
        "MONTH",
        "MON",
        "MO",
        "M",
        "MM",
    }

    DAY_PARTS = {
        "DAY",
        "D",
        "DD",
    }

    DAY_OR_YEAR_PARTS = {
        "DY",
    }

    D_PREFIX_YEAR_PARTS = {
        "DY",
    }

    D_PREFIX_MONTH_PARTS = {
        "DM",
    }

    D_PREFIX_DAY_PARTS = {
        "DD",
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

            inferred_date_rows = self.build_inferred_outer_date_rows(
                record=record,
                table=table,
                column_lookup=column_lookup,
                relationship_text=relationship_lookup.get(
                    record_name,
                    "",
                ),
            )

            emitted_inferred_dates: set[str] = set()

            for field in record.fields:
                field_name = NameNormalizer.normalize(
                    field.name,
                )

                inferred_date_key = self.inferred_date_key_for_date_part(
                    field_name=field_name,
                )

                if (
                    inferred_date_key
                    and inferred_date_key in inferred_date_rows
                    and inferred_date_key not in emitted_inferred_dates
                ):
                    rows.append(
                        inferred_date_rows[inferred_date_key],
                    )
                    emitted_inferred_dates.add(
                        inferred_date_key,
                    )

                is_date_part = self.is_date_part_name(
                    field_name=field_name,
                )

                db2_column = None

                if not is_date_part:
                    db2_column = self.find_matching_column(
                        field_name=field_name,
                        column_lookup=column_lookup,
                    )

                db2_key = self.db2_key_label(
                    table=table,
                    column=db2_column,
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
                    db2_key=db2_key,
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

                row["DB2 Key"] = db2_key

                row["New DB2 Record"] = (
                    table.name
                    if db2_column is not None
                    and table is not None
                    and getattr(table, "name", None)
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

            for inferred_date_key, inferred_date_row in inferred_date_rows.items():
                if inferred_date_key not in emitted_inferred_dates:
                    rows.append(
                        inferred_date_row,
                    )
                    emitted_inferred_dates.add(
                        inferred_date_key,
                    )

        return rows

    def build_inferred_outer_date_rows(
        self,
        record,
        table: DB2Table | None,
        column_lookup: dict[str, DB2Column],
        relationship_text: str,
    ) -> dict[str, dict[str, str]]:
        inferred_rows: dict[str, dict[str, str]] = {}

        date_groups = self.collect_date_part_groups(
            fields=getattr(
                record,
                "fields",
                [],
            )
            or [],
        )

        for date_key, group_info in date_groups.items():
            parts = group_info.get(
                "parts",
                {},
            )

            if not self.has_complete_date_group(
                parts=parts,
            ):
                continue

            candidate_names = group_info.get(
                "candidate_names",
                [],
            )

            date_column = self.find_first_matching_column(
                candidate_names=candidate_names,
                column_lookup=column_lookup,
            )

            if date_column is None:
                continue

            db2_key = self.db2_key_label(
                table=table,
                column=date_column,
            )

            display_date_name = self.best_display_date_name(
                candidate_names=candidate_names,
                date_column=date_column,
            )

            row = self.empty_row()

            row["Cobol Record IDMS"] = getattr(
                record,
                "name",
                "",
            ) or ""

            row["Cobol Zone"] = self.inferred_outer_date_cobol_zone(
                date_field_name=display_date_name,
                parts=parts,
            )

            row["IDMS Key"] = ""
            row["IDMS PIC Clause"] = ""
            row["Length of Field Bytes"] = ""
            row["Field end position"] = ""
            row["DB2 Key"] = db2_key

            row["New DB2 Record"] = (
                table.name
                if table is not None and getattr(table, "name", None)
                else ""
            )

            row["New DB2 Field_name"] = (
                date_column.name
                if getattr(date_column, "name", None)
                else ""
            )

            row["New DB2 Data Type"] = self.get_db2_datatype(
                db2_column=date_column,
            )

            row["Hopex Expression TypeRemark"] = ""
            row["Relation"] = relationship_text
            row["Reference Field Name (CopyBook) "] = ""
            row["Reference Field PIC Clause"] = ""
            row["Cross Application DB2 Field Name"] = ""
            row["Cross Appln DB2 Data Type"] = ""
            row["Basetype"] = "DATE"

            inferred_rows[date_key] = row

        return inferred_rows

    def collect_date_part_groups(
        self,
        fields,
    ) -> dict[str, dict[str, object]]:
        raw_candidates: list[dict[str, object]] = []

        for field in fields:
            field_name = getattr(
                field,
                "name",
                "",
            )

            candidates = self.parse_date_part_candidates(
                field_name=field_name,
            )

            for candidate in candidates:
                candidate["field"] = field
                raw_candidates.append(
                    candidate,
                )

        groups: dict[str, dict[str, object]] = {}

        for candidate in raw_candidates:
            date_key = str(
                candidate["date_key"],
            )

            part = str(
                candidate["part"],
            )

            if date_key not in groups:
                groups[date_key] = {
                    "parts": {},
                    "candidate_names": candidate.get(
                        "candidate_names",
                        [],
                    ),
                }

            parts = groups[date_key]["parts"]

            if isinstance(parts, dict):
                parts[part] = candidate.get(
                    "field",
                )

            existing_candidate_names = groups[date_key].get(
                "candidate_names",
                [],
            )

            if isinstance(existing_candidate_names, list):
                for name in candidate.get(
                    "candidate_names",
                    [],
                ):
                    if name not in existing_candidate_names:
                        existing_candidate_names.append(
                            name,
                        )

        return groups

    def parse_date_part_candidates(
        self,
        field_name: str,
    ) -> list[dict[str, object]]:
        tokens = self.split_name_tokens(
            field_name,
        )

        if len(tokens) < 2:
            return []

        candidates: list[dict[str, object]] = []

        for index, token in enumerate(tokens):
            upper_token = token.upper()

            possible_parts = self.possible_date_parts(
                token=upper_token,
                tokens=tokens,
            )

            for part in possible_parts:
                base_tokens = tokens[:index] + tokens[index + 1 :]

                if not base_tokens:
                    continue

                date_tokens = tokens.copy()
                date_tokens[index] = "DATE"

                base_name = " ".join(
                    base_tokens,
                )

                date_name = " ".join(
                    date_tokens,
                )

                candidate_names = self.unique_values(
                    [
                        date_name,
                        base_name,
                    ]
                )

                date_key = self.date_group_key(
                    base_name=base_name,
                )

                candidates.append(
                    {
                        "date_key": date_key,
                        "part": part,
                        "candidate_names": candidate_names,
                    }
                )

        return candidates

    def possible_date_parts(
        self,
        token: str,
        tokens: list[str],
    ) -> list[str]:
        upper_tokens = {
            value.upper()
            for value in tokens
        }

        has_d_prefix_pattern = bool(
            upper_tokens
            & (
                self.D_PREFIX_YEAR_PARTS
                | self.D_PREFIX_MONTH_PARTS
                | self.D_PREFIX_DAY_PARTS
            )
        )

        if token in self.YEAR_PARTS:
            return [
                "YEAR",
            ]

        if token in self.MONTH_PARTS:
            return [
                "MONTH",
            ]

        if token in self.DAY_PARTS:
            return [
                "DAY",
            ]

        if token in self.D_PREFIX_MONTH_PARTS:
            return [
                "MONTH",
            ]

        if token in self.D_PREFIX_DAY_PARTS:
            return [
                "DAY",
            ]

        if token in self.D_PREFIX_YEAR_PARTS:
            if has_d_prefix_pattern:
                return [
                    "YEAR",
                ]

            return [
                "DAY",
                "YEAR",
            ]

        return []

    def inferred_date_key_for_date_part(
        self,
        field_name: str,
    ) -> str | None:
        candidates = self.parse_date_part_candidates(
            field_name=field_name,
        )

        if not candidates:
            return None

        return str(
            candidates[0]["date_key"],
        )

    def has_complete_date_group(
        self,
        parts: dict[str, object],
    ) -> bool:
        return (
            "YEAR" in parts
            and "MONTH" in parts
            and "DAY" in parts
        )

    def date_group_key(
        self,
        base_name: str,
    ) -> str:
        return NameNormalizer.normalize(
            base_name,
        )

    def find_first_matching_column(
        self,
        candidate_names: list[str],
        column_lookup: dict[str, DB2Column],
    ) -> DB2Column | None:
        for candidate_name in candidate_names:
            column = self.find_matching_column(
                field_name=NameNormalizer.normalize(
                    candidate_name,
                ),
                column_lookup=column_lookup,
            )

            if column is not None:
                return column

        return None

    def best_display_date_name(
        self,
        candidate_names: list[str],
        date_column: DB2Column,
    ) -> str:
        column_name = getattr(
            date_column,
            "name",
            "",
        )

        for candidate_name in candidate_names:
            if self.same_column_name(
                left=candidate_name,
                right=column_name,
            ):
                return candidate_name

        if candidate_names:
            return candidate_names[0]

        return column_name

    def inferred_outer_date_cobol_zone(
        self,
        date_field_name: str,
        parts: dict[str, object],
    ) -> str:
        first_part_field = (
            parts.get("YEAR")
            or parts.get("MONTH")
            or parts.get("DAY")
        )

        level = getattr(
            first_part_field,
            "level",
            None,
        )

        inferred_level = None

        if level is not None:
            try:
                inferred_level = max(
                    int(level) - 1,
                    1,
                )
            except Exception:
                inferred_level = level

        display_name = self.to_cobol_name(
            value=date_field_name,
        )

        return self.format_cobol_level_and_name(
            level=inferred_level,
            name=display_name,
        )

    def unique_values(
        self,
        values: list[str],
    ) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()

        for value in values:
            normalized = NameNormalizer.normalize(
                value,
            )

            if not normalized:
                continue

            if normalized in seen:
                continue

            seen.add(
                normalized,
            )

            result.append(
                normalized,
            )

        return result

    def to_cobol_name(
        self,
        value: str,
    ) -> str:
        tokens = self.split_name_tokens(
            value,
        )

        return "-".join(
            tokens,
        )

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

        return None

    def build_cobol_zone_value(
        self,
        record,
        field,
        db2_column: DB2Column | None,
    ) -> str:
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
        db2_key: str,
    ) -> str:
        labels: list[str] = []

        if self.is_calc_key_field(
            record=record,
            field=field,
        ):
            labels.append(
                "CALC",
            )

        if self.db2_key_contains_fk(
            db2_key=db2_key,
        ):
            labels.append(
                "SET",
            )

        return "; ".join(
            labels,
        )

    def db2_key_contains_fk(
        self,
        db2_key: str,
    ) -> bool:
        parts = [
            part.strip().upper()
            for part in str(db2_key or "").split("/")
            if part.strip()
        ]

        return "FK" in parts

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
        column_name = getattr(
            column,
            "name",
            None,
        )

        if not column_name:
            return False

        for foreign_key in getattr(table, "foreign_keys", []) or []:
            foreign_key_column_name = self.get_foreign_key_column_name(
                foreign_key=foreign_key,
            )

            if self.same_column_name(
                left=foreign_key_column_name,
                right=column_name,
            ):
                return True

        return False

    def get_foreign_key_column_name(
        self,
        foreign_key,
    ) -> str:
        return (
            getattr(foreign_key, "column_name", None)
            or getattr(foreign_key, "child_column", None)
            or getattr(foreign_key, "child_fk", None)
            or getattr(foreign_key, "foreign_key", None)
            or getattr(foreign_key, "column", None)
            or ""
        )

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

    def is_date_part_name(
        self,
        field_name: str,
    ) -> bool:
        return bool(
            self.parse_date_part_candidates(
                field_name=field_name,
            )
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