import re

from idms_modernizer.domain.db2_models import (
    DB2Model,
    DB2Table,
    DB2Column,
)
from idms_modernizer.domain.schema_models import SchemaMetadata
from idms_modernizer.services.name_normalizer import NameNormalizer
from idms_modernizer.services.db2_datatype_mapper import DB2DatatypeMapper


print("LOADED ExcelSheetMappingService VERSION FULL-LATEST-CALC-PIC-DATE-FK-NAMING-2026-07-29")


class ExcelSheetMappingService:
    """
    Builds Excel Sheet Mapping rows.

    Rules:
    - Always add level 01 record row if missing.
    - Include all outer/group rows from mapping_fields.
    - Group rows do not create DB2 physical field names.
    - Outer CALC group does not show CALC.
    - Inner groups under CALC also do not show CALC or PK.
    - Only elementary non-date descendants of CALC show CALC and PK.
    - Date groups and date parts inside CALC show neither CALC nor PK.
    - FILLER rows are COBOL-only.
    - Outer date group shows DB2 record and DATE datatype.
    - Date parts remain visible but DB2 mapping stays blank.
    - Sheet Mapping DB2 datatype is calculated directly from IDMS PIC Clause.
    - Field end position = STRT + LGTH - 1.
    - SET/FK rows reuse referenced/master DB2 column names.
    - DB2 field names use project naming rules and _479<record-code>.
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
        "New DB2 Field name",
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
        "DY",
    }

    MONTH_PARTS = {
        "MONTH",
        "MON",
        "MO",
        "M",
        "MM",
        "DM",
    }

    DAY_PARTS = {
        "DAY",
        "D",
        "DD",
    }

    DATE_TOKENS = {
        "DATE",
        "DT",
        "DTE",
        "DA",
        "YYMMDD",
        "YYYYMMDD",
        "YMD",
    }

    DATE_CHILD_TOKENS = YEAR_PARTS | MONTH_PARTS | DAY_PARTS

    PROJECT_ABBREVIATIONS = {
        "FORM": "FM",
        "EVPRCP": "ERCP",
    }

    GENERIC_TRAILING_TOKENS = {
        "SIC",
        "FC",
        "GDIFC",
        "GDIFR",
        "GDIFAR",
        "GDIF",
        "GDI",
        "REC",
        "RECORD",
    }

    DATE_TRAILING_TOKENS = {
        "SIC",
        "FC",
        "GDIFC",
        "GDIFR",
        "GDIF",
        "GDI",
    }

    def build(
        self,
        metadata: SchemaMetadata,
        db2_model: DB2Model,
    ) -> list[dict[str, str]]:
        print("USING ExcelSheetMappingService.build VERSION FULL-LATEST-CALC-PIC-DATE-FK-NAMING-2026-07-29")

        rows: list[dict[str, str]] = []

        table_lookup = self.build_table_lookup(
            db2_model=db2_model,
        )

        relationship_lookup = self.build_relationship_lookup(
            metadata=metadata,
        )

        for record in getattr(metadata, "records", []) or []:
            mapping_fields = (
                getattr(record, "mapping_fields", None)
                or getattr(record, "fields", None)
                or []
            )

            if not self.has_level_01_row(
                record=record,
                mapping_fields=mapping_fields,
            ):
                rows.append(
                    self.build_record_level_01_row(
                        record=record,
                    )
                )

            table = self.find_table_for_record(
                record_name=getattr(record, "name", "") or "",
                table_lookup=table_lookup,
            )

            rows.extend(
                self.build_record_mapping_rows(
                    record=record,
                    table=table,
                    relationship_lookup=relationship_lookup,
                )
            )

            rows.extend(
                self.build_generated_pk_rows(
                    record=record,
                    table=table,
                )
            )

            rows.extend(
                self.build_audit_rows(
                    record=record,
                    table=table,
                )
            )

            rows.extend(
                self.build_set_fk_rows_for_record(
                    metadata=metadata,
                    record=record,
                    table=table,
                    table_lookup=table_lookup,
                )
            )

        rows = self.force_pic_based_datatypes(
            rows=rows,
        )

        return rows

    def build_record_mapping_rows(
        self,
        record,
        table: DB2Table | None,
        relationship_lookup: dict[str, str],
    ) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []

        mapping_fields = (
            getattr(record, "mapping_fields", None)
            or getattr(record, "fields", None)
            or []
        )

        column_lookup = (
            self.build_column_lookup(table=table)
            if table is not None
            else {}
        )

        date_scope = self.build_date_scope(
            fields=mapping_fields,
        )

        date_group_info = self.collect_date_group_info(
            fields=mapping_fields,
        )

        calc_scope = self.build_calc_scope(
            record=record,
            fields=mapping_fields,
        )

        for field in mapping_fields:
            if self.is_filler_field(field=field):
                rows.append(
                    self.build_filler_row(
                        record=record,
                        field=field,
                    )
                )
                continue

            is_group = self.is_group_field(
                field=field,
            )

            is_outer_date = self.is_outer_date_group(
                field=field,
                date_group_info=date_group_info,
            )

            is_date_child = self.is_date_child(
                field=field,
                date_scope=date_scope,
            )

            is_direct_date = self.is_direct_date_field(
                field=field,
            )

            is_date = (
                is_outer_date
                or is_date_child
                or is_direct_date
            )

            calc_status = self.calc_status_for_field(
                field=field,
                calc_scope=calc_scope,
            )

            db2_column = self.find_column_for_field(
                record=record,
                field=field,
                column_lookup=column_lookup,
            )

            db2_key = self.db2_key_label(
                table=table,
                column=db2_column,
            )

            if calc_status == "ROOT":
                db2_key = ""

            if is_group:
                db2_key = ""

            if calc_status == "DESCENDANT" and not is_date and not is_group:
                db2_key = self.add_pk_to_db2_key(
                    db2_key=db2_key,
                )

            if is_date:
                db2_key = ""

            row = self.empty_row()

            row["Cobol Record IDMS"] = getattr(record, "name", "") or ""
            row["Cobol Zone"] = self.format_cobol_zone(field=field)
            row["IDMS Key"] = self.idms_key_label(
                calc_status=calc_status,
                is_date=is_date,
                is_group=is_group,
                db2_key=db2_key,
            )
            row["IDMS PIC Clause"] = self.get_field_picture(field=field)
            row["Length of Field Bytes"] = self.to_string(
                self.get_field_length(field=field)
            )
            row["Field end position"] = self.to_string(
                self.get_field_end_position(field=field)
            )
            row["DB2 Key"] = db2_key

            if is_outer_date:
                row["New DB2 Record"] = self.db2_record_name(
                    record=record,
                    table=table,
                )
                row["New DB2 Field name"] = self.convert_date_field_to_db2_field_name(
                    record=record,
                    field=field,
                )
                row["New DB2 Data Type"] = "DATE"
                row["DB2 Key"] = ""

            elif is_date_child:
                row["New DB2 Record"] = ""
                row["New DB2 Field name"] = ""
                row["New DB2 Data Type"] = ""
                row["DB2 Key"] = ""

            elif is_direct_date:
                row["New DB2 Record"] = self.db2_record_name(
                    record=record,
                    table=table,
                )
                row["New DB2 Field name"] = self.convert_date_field_to_db2_field_name(
                    record=record,
                    field=field,
                )
                row["New DB2 Data Type"] = "DATE"
                row["DB2 Key"] = ""

            elif calc_status == "ROOT":
                row["New DB2 Record"] = ""
                row["New DB2 Field name"] = ""
                row["New DB2 Data Type"] = ""
                row["DB2 Key"] = ""

            elif is_group:
                row["New DB2 Record"] = ""
                row["New DB2 Field name"] = ""
                row["New DB2 Data Type"] = ""
                row["DB2 Key"] = ""

            elif self.should_emit_db2_field(field=field):
                row["New DB2 Record"] = self.db2_record_name(
                    record=record,
                    table=table,
                )

                if db2_column is not None and getattr(db2_column, "name", None):
                    row["New DB2 Field name"] = getattr(db2_column, "name", "") or ""
                else:
                    row["New DB2 Field name"] = self.convert_cobol_zone_to_db2_field_name(
                        record=record,
                        field=field,
                    )

                row["New DB2 Data Type"] = self.infer_db2_datatype_from_field(
                    field=field,
                )

            row["Hopex Expression TypeRemark"] = self.hopex_remark(
                field=field,
            )
            row["Relation"] = relationship_lookup.get(
                NameNormalizer.normalize(getattr(record, "name", "") or ""),
                "",
            )
            row["Basetype"] = self.get_field_basetype(
                field=field,
            )

            rows.append(row)

        return rows

    def build_calc_scope(
        self,
        record,
        fields,
    ) -> dict[str, str]:
        scope: dict[str, str] = {}

        primary_key = getattr(record, "primary_key", None)

        if not primary_key:
            return scope

        normalized_primary_key = NameNormalizer.normalize(primary_key)
        suffix_removed_primary_key = self.remove_record_suffix(
            normalized_primary_key,
        )

        mapping_fields = list(fields or [])

        key_field = None
        key_index = None

        for index, field in enumerate(mapping_fields):
            field_name = NameNormalizer.normalize(
                getattr(field, "name", "") or ""
            )

            if not field_name:
                continue

            if field_name == normalized_primary_key:
                key_field = field
                key_index = index
                break

            if self.remove_record_suffix(field_name) == suffix_removed_primary_key:
                key_field = field
                key_index = index
                break

        if key_field is None or key_index is None:
            if normalized_primary_key:
                scope[normalized_primary_key] = "DESCENDANT"
            return scope

        key_name = NameNormalizer.normalize(
            getattr(key_field, "name", "") or ""
        )

        if not key_name:
            return scope

        key_is_group = self.is_group_field(
            field=key_field,
        )

        key_level = getattr(key_field, "level", None)

        if not key_is_group:
            scope[key_name] = "DESCENDANT"
            return scope

        scope[key_name] = "ROOT"

        if key_level is None:
            return scope

        try:
            key_level_int = int(key_level)
        except Exception:
            return scope

        for child_field in mapping_fields[key_index + 1:]:
            child_name = NameNormalizer.normalize(
                getattr(child_field, "name", "") or ""
            )
            child_level = getattr(child_field, "level", None)

            if child_level is None:
                continue

            try:
                child_level_int = int(child_level)
            except Exception:
                continue

            if child_level_int <= key_level_int:
                break

            if child_name:
                scope[child_name] = "DESCENDANT"

        return scope

    def calc_status_for_field(
        self,
        field,
        calc_scope: dict[str, str],
    ) -> str:
        field_name = NameNormalizer.normalize(
            getattr(field, "name", "") or ""
        )

        if not field_name:
            return ""

        if field_name in calc_scope:
            return calc_scope[field_name]

        suffix_removed = self.remove_record_suffix(field_name)

        for key, value in calc_scope.items():
            if self.remove_record_suffix(key) == suffix_removed:
                return value

        return ""

    def idms_key_label(
        self,
        calc_status: str,
        is_date: bool,
        is_group: bool,
        db2_key: str,
    ) -> str:
        if is_date:
            return ""

        if is_group:
            return ""

        labels: list[str] = []

        if calc_status == "DESCENDANT":
            labels.append("CALC")

        db2_key_parts = [
            part.strip().upper()
            for part in str(db2_key or "").split("/")
            if part.strip()
        ]

        if "FK" in db2_key_parts:
            labels.append("SET")

        output: list[str] = []

        for label in labels:
            if label not in output:
                output.append(label)

        return "; ".join(output)

    def add_pk_to_db2_key(
        self,
        db2_key: str,
    ) -> str:
        parts = [
            part.strip().upper()
            for part in str(db2_key or "").split("/")
            if part.strip()
        ]

        if "PK" not in parts:
            parts.insert(0, "PK")

        ordered_parts: list[str] = []

        if "PK" in parts:
            ordered_parts.append("PK")

        if "FK" in parts:
            ordered_parts.append("FK")

        return "/".join(ordered_parts)

    def force_pic_based_datatypes(
        self,
        rows: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        corrected_rows: list[dict[str, str]] = []

        for row in rows or []:
            pic_clause = str(row.get("IDMS PIC Clause", "") or "").strip()
            db2_record = str(row.get("New DB2 Record", "") or "").strip()
            db2_field = str(row.get("New DB2 Field name", "") or "").strip()
            current_type = str(row.get("New DB2 Data Type", "") or "").strip().upper()

            if current_type == "DATE":
                corrected_rows.append(row)
                continue

            if pic_clause and db2_record and db2_field:
                row["New DB2 Data Type"] = DB2DatatypeMapper.map_picture(
                    picture=pic_clause,
                    fallback_length=None,
                    fallback_scale=None,
                )

            corrected_rows.append(row)

        return corrected_rows

    def build_table_lookup(
        self,
        db2_model: DB2Model,
    ) -> dict[str, DB2Table]:
        lookup: dict[str, DB2Table] = {}

        if db2_model is None:
            return lookup

        for table in getattr(db2_model, "tables", []) or []:
            table_name = getattr(table, "name", "") or ""

            for key in self.name_lookup_keys(table_name):
                lookup[key] = table

        return lookup

    def build_column_lookup(
        self,
        table: DB2Table,
    ) -> dict[str, DB2Column]:
        lookup: dict[str, DB2Column] = {}

        for column in getattr(table, "columns", []) or []:
            column_name = getattr(column, "name", "") or ""

            for key in self.name_lookup_keys(column_name):
                lookup[key] = column

        return lookup

    def build_relationship_lookup(
        self,
        metadata: SchemaMetadata,
    ) -> dict[str, str]:
        lookup: dict[str, str] = {}

        for relationship in getattr(metadata, "relationships", []) or []:
            owner_record = self.get_relationship_owner_record(relationship=relationship)
            member_record = self.get_relationship_member_record(relationship=relationship)
            set_name = self.get_relationship_set_name(relationship=relationship)

            for record_name in [owner_record, member_record]:
                normalized_record = NameNormalizer.normalize(record_name)

                if not normalized_record:
                    continue

                existing = lookup.get(normalized_record, "")

                if existing:
                    if set_name and set_name not in existing:
                        lookup[normalized_record] = f"{existing}; {set_name}"
                else:
                    lookup[normalized_record] = set_name

        return lookup

    def build_date_scope(
        self,
        fields,
    ) -> dict[int, bool]:
        scope: dict[int, bool] = {}
        active_date_levels: list[int] = []

        for field in fields or []:
            level = self.safe_int(getattr(field, "level", None), default=0)

            active_date_levels = [
                current_level
                for current_level in active_date_levels
                if current_level < level
            ]

            if active_date_levels:
                scope[id(field)] = True

            if self.is_potential_outer_date(field=field):
                active_date_levels.append(level)

        return scope

    def collect_date_group_info(
        self,
        fields,
    ) -> dict[str, dict]:
        info: dict[str, dict] = {}

        for index, field in enumerate(fields or []):
            if not self.is_group_field(field=field):
                continue

            if not self.is_potential_outer_date(field=field):
                continue

            if not self.group_has_ymd_children(
                field=field,
                fields=fields,
                start_index=index,
            ):
                continue

            field_name = NameNormalizer.normalize(getattr(field, "name", "") or "")

            if field_name:
                info[field_name] = {"field": field}

        return info

    def group_has_ymd_children(
        self,
        field,
        fields,
        start_index: int,
    ) -> bool:
        parent_level = self.safe_int(getattr(field, "level", None), default=0)

        found_year = False
        found_month = False
        found_day = False

        for child in list(fields or [])[start_index + 1:]:
            child_level = self.safe_int(getattr(child, "level", None), default=0)

            if child_level <= parent_level:
                break

            child_name = getattr(child, "name", "") or ""
            parts = self.name_parts(child_name)

            if any(part in self.YEAR_PARTS for part in parts):
                found_year = True

            if any(part in self.MONTH_PARTS for part in parts):
                found_month = True

            if any(part in self.DAY_PARTS for part in parts):
                found_day = True

        return found_year and found_month and found_day

    def is_outer_date_group(
        self,
        field,
        date_group_info: dict[str, dict],
    ) -> bool:
        if not self.is_group_field(field=field):
            return False

        field_name = NameNormalizer.normalize(getattr(field, "name", "") or "")

        return field_name in date_group_info

    def is_date_child(
        self,
        field,
        date_scope: dict[int, bool],
    ) -> bool:
        if id(field) not in date_scope:
            return False

        return self.is_date_part_name(field_name=getattr(field, "name", "") or "")

    def is_direct_date_field(
        self,
        field,
    ) -> bool:
        if self.is_group_field(field=field):
            return False

        datatype = str(
            getattr(field, "datatype", None)
            or getattr(field, "data_type", None)
            or getattr(field, "type", None)
            or "",
        ).strip().upper()

        basetype = str(
            getattr(field, "basetype", None)
            or getattr(field, "base_type", None)
            or "",
        ).strip().upper()

        if datatype == "DATE" or basetype == "DATE":
            return not self.is_date_part_name(field_name=getattr(field, "name", "") or "")

        pic_clause = self.get_field_picture(field=field)

        if self.is_date_like_name(getattr(field, "name", "") or "") and self.is_yyyymmdd_picture(pic_clause):
            return True

        return False

    def is_potential_outer_date(
        self,
        field,
    ) -> bool:
        field_name = getattr(field, "name", "") or ""

        if self.is_date_like_name(field_name):
            return True

        datatype = str(
            getattr(field, "datatype", None)
            or getattr(field, "data_type", None)
            or getattr(field, "type", None)
            or "",
        ).strip().upper()

        basetype = str(
            getattr(field, "basetype", None)
            or getattr(field, "base_type", None)
            or "",
        ).strip().upper()

        return datatype == "DATE" or basetype == "DATE"

    def is_date_part_name(
        self,
        field_name: str,
    ) -> bool:
        parts = self.name_parts(field_name or "")

        return any(part in self.DATE_CHILD_TOKENS for part in parts)

    def is_yyyymmdd_picture(
        self,
        pic_clause: str,
    ) -> bool:
        clean = DB2DatatypeMapper.clean_picture(pic_clause)
        core = DB2DatatypeMapper.picture_core(clean)

        return core in {"9(8)", "S9(8)", "99999999", "S99999999"}

    def is_date_like_name(
        self,
        value: str,
    ) -> bool:
        parts = self.name_parts(value or "")

        if any(part in self.DATE_TOKENS for part in parts):
            return True

        if parts and parts[0] == "DA":
            return True

        compact = "".join(parts)

        return any(token in compact for token in self.DATE_TOKENS)

    def find_table_for_record(
        self,
        record_name: str,
        table_lookup: dict[str, DB2Table],
    ) -> DB2Table | None:
        for key in self.name_lookup_keys(record_name):
            if key in table_lookup:
                return table_lookup[key]

        return None

    def find_column_for_field(
        self,
        record,
        field,
        column_lookup: dict[str, DB2Column],
    ) -> DB2Column | None:
        field_name = getattr(field, "name", "") or ""

        if not field_name:
            return None

        possible_names = [
            field_name,
            self.remove_record_suffix(field_name),
            self.cobol_field_base_name(field_name=field_name),
            self.date_field_base_name(field_name=field_name),
            self.convert_cobol_zone_to_db2_field_name(record=record, field=field),
            self.convert_date_field_to_db2_field_name(record=record, field=field),
        ]

        for name in possible_names:
            column = self.find_matching_column(
                normalized_column_name=name,
                column_lookup=column_lookup,
            )

            if column is not None:
                return column

        return None

    def find_matching_column(
        self,
        normalized_column_name: str,
        column_lookup: dict[str, DB2Column],
    ) -> DB2Column | None:
        for key in self.name_lookup_keys(normalized_column_name):
            if key in column_lookup:
                return column_lookup[key]

        suffix_removed = self.remove_record_suffix(normalized_column_name)

        for key in self.name_lookup_keys(suffix_removed):
            if key in column_lookup:
                return column_lookup[key]

        target_suffix_removed = self.remove_record_suffix(
            self.to_db2_name(normalized_column_name)
        )

        for current_name, column in column_lookup.items():
            if self.remove_record_suffix(current_name) == target_suffix_removed:
                return column

        return None

    def build_filler_row(
        self,
        record,
        field,
    ) -> dict[str, str]:
        row = self.empty_row()

        row["Cobol Record IDMS"] = getattr(record, "name", "") or ""
        row["Cobol Zone"] = self.format_cobol_zone(field=field)
        row["IDMS PIC Clause"] = self.get_field_picture(field=field)
        row["Length of Field Bytes"] = self.to_string(self.get_field_length(field=field))
        row["Field end position"] = self.to_string(self.get_field_end_position(field=field))

        return row

    def build_generated_pk_rows(
        self,
        record,
        table: DB2Table | None,
    ) -> list[dict[str, str]]:
        if table is None:
            return []

        rows: list[dict[str, str]] = []

        for column in getattr(table, "columns", []) or []:
            if getattr(column, "source_kind", "") != "GENERATED PK":
                continue

            row = self.empty_row()
            row["Cobol Record IDMS"] = getattr(record, "name", "") or ""
            row["DB2 Key"] = "PK"
            row["New DB2 Record"] = getattr(table, "name", "") or ""
            row["New DB2 Field name"] = getattr(column, "name", "") or ""
            row["New DB2 Data Type"] = self.get_db2_datatype(db2_column=column)
            rows.append(row)

        return rows

    def build_audit_rows(
        self,
        record,
        table: DB2Table | None,
    ) -> list[dict[str, str]]:
        if table is None:
            return []

        rows: list[dict[str, str]] = []
        record_name = getattr(record, "name", "") or ""
        normalized_record_name = self.to_db2_name(record_name)

        audit_fields = [
            (f"TS_CREATE_{normalized_record_name}", "TIMESTAMP"),
            (f"TS_UPDATE_{normalized_record_name}", "TIMESTAMP"),
            (f"ID_USERID_{normalized_record_name}", "CHAR(8)"),
        ]

        for field_name, datatype in audit_fields:
            row = self.empty_row()
            row["Cobol Record IDMS"] = record_name
            row["New DB2 Record"] = getattr(table, "name", "") or ""
            row["New DB2 Field name"] = field_name
            row["New DB2 Data Type"] = datatype
            rows.append(row)

        return rows

    def build_set_fk_rows_for_record(
        self,
        metadata: SchemaMetadata,
        record,
        table: DB2Table | None,
        table_lookup: dict[str, DB2Table],
    ) -> list[dict[str, str]]:
        if table is None:
            return []

        rows: list[dict[str, str]] = []
        emitted: set[tuple[str, str, str, str]] = set()

        rows.extend(
            self.build_set_fk_rows_from_db2_foreign_keys(
                record=record,
                table=table,
                emitted=emitted,
            )
        )

        rows.extend(
            self.build_set_fk_rows_from_metadata_relationships(
                metadata=metadata,
                record=record,
                member_table=table,
                table_lookup=table_lookup,
                emitted=emitted,
            )
        )

        return rows

    def build_set_fk_rows_from_db2_foreign_keys(
        self,
        record,
        table: DB2Table,
        emitted: set[tuple[str, str, str, str]],
    ) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        cobol_record_name = getattr(record, "name", "") or ""

        column_lookup = self.build_column_lookup(table=table)

        for foreign_key in getattr(table, "foreign_keys", []) or []:
            fk_column_name = self.get_foreign_key_column_name(foreign_key=foreign_key)

            if not fk_column_name:
                continue

            fk_column = self.find_matching_column(
                normalized_column_name=fk_column_name,
                column_lookup=column_lookup,
            )

            if fk_column is None:
                continue

            fk_datatype = self.get_db2_datatype(db2_column=fk_column)
            set_name = getattr(foreign_key, "set_name", "") or ""

            key = (
                NameNormalizer.normalize(cobol_record_name),
                NameNormalizer.normalize(getattr(table, "name", "") or ""),
                NameNormalizer.normalize(getattr(fk_column, "name", "") or ""),
                fk_datatype,
            )

            if key in emitted:
                continue

            emitted.add(key)

            row = self.empty_row()
            row["Cobol Record IDMS"] = cobol_record_name
            row["IDMS Key"] = "SET"
            row["DB2 Key"] = "FK"
            row["New DB2 Record"] = getattr(table, "name", "") or ""
            row["New DB2 Field name"] = getattr(fk_column, "name", "") or ""
            row["New DB2 Data Type"] = fk_datatype
            row["Relation"] = set_name
            rows.append(row)

        return rows

    def build_set_fk_rows_from_metadata_relationships(
        self,
        metadata: SchemaMetadata,
        record,
        member_table: DB2Table,
        table_lookup: dict[str, DB2Table],
        emitted: set[tuple[str, str, str, str]],
    ) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []

        cobol_record_name = getattr(record, "name", "") or ""
        normalized_current_record = NameNormalizer.normalize(cobol_record_name)
        normalized_current_table = NameNormalizer.normalize(getattr(member_table, "name", "") or "")

        for relationship in getattr(metadata, "relationships", []) or []:
            set_name = self.get_relationship_set_name(relationship=relationship)
            owner_record_name = self.get_relationship_owner_record(relationship=relationship)
            member_record_name = self.get_relationship_member_record(relationship=relationship)

            if not set_name:
                continue

            normalized_member_record = NameNormalizer.normalize(member_record_name)

            if normalized_member_record not in {normalized_current_record, normalized_current_table}:
                continue

            owner_table = self.find_table_for_record(
                record_name=owner_record_name,
                table_lookup=table_lookup,
            )

            owner_pk_column = self.find_primary_key_column(table=owner_table)

            if owner_pk_column is None:
                continue

            fk_column_name = getattr(owner_pk_column, "name", "") or ""
            fk_datatype = self.get_db2_datatype(db2_column=owner_pk_column)

            key = (
                NameNormalizer.normalize(cobol_record_name),
                NameNormalizer.normalize(getattr(member_table, "name", "") or ""),
                NameNormalizer.normalize(fk_column_name),
                fk_datatype,
            )

            if key in emitted:
                continue

            emitted.add(key)

            row = self.empty_row()
            row["Cobol Record IDMS"] = cobol_record_name
            row["IDMS Key"] = "SET"
            row["DB2 Key"] = "FK"
            row["New DB2 Record"] = getattr(member_table, "name", "") or ""
            row["New DB2 Field name"] = fk_column_name
            row["New DB2 Data Type"] = fk_datatype
            row["Relation"] = set_name
            rows.append(row)

        return rows

    def find_primary_key_column(
        self,
        table: DB2Table | None,
    ) -> DB2Column | None:
        if table is None:
            return None

        primary_key_names = list(getattr(table, "primary_keys", []) or [])

        if not primary_key_names and getattr(table, "primary_key", None):
            primary_key_names = [table.primary_key]

        normalized_primary_keys = {
            NameNormalizer.normalize(primary_key)
            for primary_key in primary_key_names
            if primary_key
        }

        for column in getattr(table, "columns", []) or []:
            column_name = NameNormalizer.normalize(getattr(column, "name", "") or "")

            if column_name in normalized_primary_keys:
                return column

            if getattr(column, "primary_key", False):
                return column

        columns = list(getattr(table, "columns", []) or [])

        return columns[0] if columns else None

    def get_foreign_key_column_name(
        self,
        foreign_key,
    ) -> str:
        if isinstance(foreign_key, dict):
            return str(
                foreign_key.get("column_name")
                or foreign_key.get("column")
                or foreign_key.get("fk_column")
                or foreign_key.get("foreign_key_column")
                or "",
            )

        return str(
            getattr(foreign_key, "column_name", None)
            or getattr(foreign_key, "column", None)
            or getattr(foreign_key, "fk_column", None)
            or getattr(foreign_key, "foreign_key_column", None)
            or "",
        )

    def get_relationship_set_name(
        self,
        relationship,
    ) -> str:
        if isinstance(relationship, dict):
            return str(
                relationship.get("set_name")
                or relationship.get("set")
                or relationship.get("name")
                or "",
            )

        return str(
            getattr(relationship, "set_name", None)
            or getattr(relationship, "set", None)
            or getattr(relationship, "name", None)
            or "",
        )

    def get_relationship_owner_record(
        self,
        relationship,
    ) -> str:
        if isinstance(relationship, dict):
            return str(
                relationship.get("owner_record")
                or relationship.get("parent_record")
                or relationship.get("owner")
                or relationship.get("parent")
                or "",
            )

        return str(
            getattr(relationship, "owner_record", None)
            or getattr(relationship, "parent_record", None)
            or getattr(relationship, "owner", None)
            or getattr(relationship, "parent", None)
            or "",
        )

    def get_relationship_member_record(
        self,
        relationship,
    ) -> str:
        if isinstance(relationship, dict):
            return str(
                relationship.get("member_record")
                or relationship.get("child_record")
                or relationship.get("member")
                or relationship.get("child")
                or "",
            )

        return str(
            getattr(relationship, "member_record", None)
            or getattr(relationship, "child_record", None)
            or getattr(relationship, "member", None)
            or getattr(relationship, "child", None)
            or "",
        )

    def get_db2_datatype(
        self,
        db2_column: DB2Column | None,
    ) -> str:
        if db2_column is None:
            return ""

        return str(
            getattr(db2_column, "datatype", None)
            or getattr(db2_column, "data_type", None)
            or getattr(db2_column, "type", None)
            or "",
        ).strip().upper()

    def db2_key_label(
        self,
        table: DB2Table | None,
        column: DB2Column | None,
    ) -> str:
        if table is None or column is None:
            return ""

        labels: list[str] = []

        if self.is_primary_key_column(table=table, column=column):
            labels.append("PK")

        if self.is_foreign_key_column(table=table, column=column):
            labels.append("FK")

        return "/".join(labels)

    def is_primary_key_column(
        self,
        table: DB2Table,
        column: DB2Column,
    ) -> bool:
        if getattr(column, "primary_key", False):
            return True

        column_name = NameNormalizer.normalize(getattr(column, "name", "") or "")
        primary_keys = list(getattr(table, "primary_keys", []) or [])

        if not primary_keys and getattr(table, "primary_key", None):
            primary_keys = [table.primary_key]

        normalized_primary_keys = {
            NameNormalizer.normalize(primary_key)
            for primary_key in primary_keys
            if primary_key
        }

        return column_name in normalized_primary_keys

    def is_foreign_key_column(
        self,
        table: DB2Table,
        column: DB2Column,
    ) -> bool:
        column_name = NameNormalizer.normalize(getattr(column, "name", "") or "")

        for foreign_key in getattr(table, "foreign_keys", []) or []:
            fk_column_name = NameNormalizer.normalize(self.get_foreign_key_column_name(foreign_key))

            if fk_column_name == column_name:
                return True

        source_kind = str(getattr(column, "source_kind", "") or "").upper()

        return source_kind in {"SET_FK", "FK", "FOREIGN KEY"}

    def should_emit_db2_field(
        self,
        field,
    ) -> bool:
        if self.is_filler_field(field=field):
            return False

        if self.is_group_field(field=field):
            return False

        if self.is_date_part_name(field_name=getattr(field, "name", "") or ""):
            return False

        picture = self.get_field_picture(field=field)

        if picture:
            return True

        datatype = str(getattr(field, "datatype", "") or "").upper()

        return datatype in {"CHAR", "VARCHAR", "DECIMAL", "NUMERIC", "DATE"}

    def is_filler_field(
        self,
        field,
    ) -> bool:
        return NameNormalizer.normalize(getattr(field, "name", "") or "") == "FILLER"

    def is_group_field(
        self,
        field,
    ) -> bool:
        return bool(getattr(field, "has_child", False) or getattr(field, "is_group", False))

    def db2_record_name(
        self,
        record,
        table: DB2Table | None,
    ) -> str:
        if table is not None and getattr(table, "name", None):
            return getattr(table, "name", "") or ""

        return self.to_db2_name(getattr(record, "name", "") or "")

    def convert_cobol_zone_to_db2_field_name(
        self,
        record,
        field,
    ) -> str:
        field_name = getattr(field, "name", "") or ""
        base = self.cobol_field_base_name(field_name=field_name)
        record_code = self.record_code(record_name=getattr(record, "name", "") or "")

        if record_code:
            return f"{base}_479{record_code}"

        return base

    def convert_date_field_to_db2_field_name(
        self,
        record,
        field,
    ) -> str:
        field_name = getattr(field, "name", "") or ""
        base = self.date_field_base_name(field_name=field_name)
        record_code = self.record_code(record_name=getattr(record, "name", "") or "")

        if record_code:
            return f"{base}_479{record_code}"

        return base

    def cobol_field_base_name(
        self,
        field_name: str,
    ) -> str:
        normalized = self.to_db2_name(field_name)
        normalized = self.remove_record_suffix(normalized)

        parts = [
            part
            for part in normalized.split("_")
            if part
        ]

        if not parts:
            return normalized

        parts = self.remove_generic_trailing_tokens(parts=parts)

        parts = [
            self.PROJECT_ABBREVIATIONS.get(part, part)
            for part in parts
        ]

        if len(parts) == 1:
            return parts[0]

        first = parts[0]
        rest = "".join(parts[1:])

        if rest:
            return f"{first}_{rest}"

        return first

    def date_field_base_name(
        self,
        field_name: str,
    ) -> str:
        normalized = self.to_db2_name(field_name)
        normalized = self.remove_record_suffix(normalized)

        parts = [
            part
            for part in normalized.split("_")
            if part
        ]

        if not parts:
            return normalized

        if parts[0] == "DA":
            main_parts = parts[1:]
        else:
            main_parts = parts

        if not main_parts:
            return "DA"

        if main_parts[0] in {"UB", "UE"}:
            return f"DA_{main_parts[0]}DATE"

        main_parts = self.apply_date_project_abbreviations(
            parts=main_parts,
        )

        main_parts = self.remove_generic_trailing_tokens(
            parts=main_parts,
        )

        if not main_parts:
            return "DA"

        if len(main_parts) == 1:
            main = main_parts[0]
        else:
            main = "".join(main_parts)

        return f"DA_{main}"

    def apply_date_project_abbreviations(
        self,
        parts: list[str],
    ) -> list[str]:
        output: list[str] = []

        for part in parts:
            if part == "EVPRCP":
                output.append("ERCP")
                continue

            if part == "GDIFAR":
                output.append("GD")
                continue

            if part in {"GDIFC", "GDIFR"}:
                continue

            output.append(
                self.PROJECT_ABBREVIATIONS.get(part, part)
            )

        return output

    def remove_generic_trailing_tokens(
        self,
        parts: list[str],
    ) -> list[str]:
        output = list(parts or [])

        while output and output[-1] in self.GENERIC_TRAILING_TOKENS:
            output.pop()

        return output

    def record_code(
        self,
        record_name: str,
    ) -> str:
        normalized = self.to_db2_name(record_name)
        compact = re.sub(r"[^A-Z0-9]", "", normalized)

        if len(compact) <= 4:
            return compact

        return compact[-4:]

    def get_field_picture(
        self,
        field,
    ) -> str:
        if self.is_group_field(field=field):
            return ""

        text = str(
            getattr(field, "picture", None)
            or getattr(field, "pic", None)
            or getattr(field, "pic_clause", None)
            or "",
        ).strip()

        if not text:
            return ""

        if text.upper().startswith("PIC "):
            return text

        if text.upper().startswith("PICTURE "):
            return "PIC " + text[8:].strip()

        return f"PIC {text}"

    def get_field_length(
        self,
        field,
    ):
        return (
            getattr(field, "length", None)
            or getattr(field, "storage_length", None)
            or getattr(field, "physical_length", None)
            or getattr(field, "byte_length", None)
            or getattr(field, "bytes", None)
        )

    def get_field_end_position(
        self,
        field,
    ):
        start = (
            getattr(field, "start_position", None)
            or getattr(field, "start", None)
        )

        length = self.get_field_length(field=field)

        try:
            if start is not None and length not in ("", None):
                return int(start) + int(length) - 1
        except Exception:
            pass

        end_position = (
            getattr(field, "end_position", None)
            or getattr(field, "field_end_position", None)
            or getattr(field, "end", None)
        )

        if end_position is not None:
            return end_position

        return ""

    def infer_db2_datatype_from_field(
        self,
        field,
    ) -> str:
        pic_clause = self.get_field_picture(field=field)

        if pic_clause:
            return DB2DatatypeMapper.map_picture(
                picture=pic_clause,
                fallback_length=None,
                fallback_scale=getattr(field, "scale", None),
            )

        datatype = str(getattr(field, "datatype", "") or "").upper()

        if datatype == "DATE":
            return "DATE"

        if datatype in {"TIMESTAMP", "DATETIME"}:
            return "TIMESTAMP"

        length = self.get_field_length(field=field) or 1

        if datatype in {"CHAR", "VARCHAR", "DISPLAY", "TEXT"}:
            return f"CHAR({int(length)})"

        if datatype in {"DECIMAL", "NUMERIC"}:
            scale = getattr(field, "scale", None)

            if scale is not None and int(scale) > 0:
                return f"DECIMAL({int(length)},{int(scale)})"

            return f"DECIMAL({int(length)})"

        return ""

    def get_field_basetype(
        self,
        field,
    ) -> str:
        return str(
            getattr(field, "basetype", None)
            or getattr(field, "base_type", None)
            or getattr(field, "datatype", None)
            or "",
        )

    def hopex_remark(
        self,
        field,
    ) -> str:
        if getattr(field, "occurs", False):
            occurs_min = getattr(field, "occurs_min", None)
            occurs_max = getattr(field, "occurs_max", None)

            if occurs_min is not None and occurs_max is not None:
                if occurs_min == occurs_max:
                    return f"OCCURS {occurs_max}"

                return f"OCCURS {occurs_min} TO {occurs_max}"

        return ""

    def has_level_01_row(
        self,
        record,
        mapping_fields,
    ) -> bool:
        record_name = NameNormalizer.normalize(getattr(record, "name", "") or "")

        for field in mapping_fields or []:
            level = getattr(field, "level", None)

            try:
                if int(level) != 1:
                    continue
            except Exception:
                continue

            field_name = NameNormalizer.normalize(getattr(field, "name", "") or "")

            if field_name == record_name:
                return True

            if self.remove_record_suffix(field_name) == self.remove_record_suffix(record_name):
                return True

        return False

    def build_record_level_01_row(
        self,
        record,
    ) -> dict[str, str]:
        row = self.empty_row()

        record_name = getattr(record, "name", "") or ""

        row["Cobol Record IDMS"] = record_name
        row["Cobol Zone"] = self.format_cobol_level_and_name(level=1, name=record_name)

        return row

    def name_lookup_keys(
        self,
        value: str,
    ) -> list[str]:
        keys: list[str] = []

        candidates = [
            value,
            NameNormalizer.normalize(value or ""),
            self.to_db2_name(value or ""),
            self.remove_record_suffix(value or ""),
            self.remove_record_suffix(NameNormalizer.normalize(value or "")),
            self.remove_record_suffix(self.to_db2_name(value or "")),
        ]

        for candidate in candidates:
            candidate_text = str(candidate or "").strip()

            if not candidate_text:
                continue

            normalized_name = NameNormalizer.normalize(candidate_text)
            db2_name = self.to_db2_name(candidate_text)

            for key in [candidate_text, normalized_name, db2_name]:
                key = str(key or "").strip()

                if key and key not in keys:
                    keys.append(key)

        return keys

    def format_cobol_zone(
        self,
        field,
    ) -> str:
        level = getattr(field, "level", None)
        name = getattr(field, "name", "") or ""

        return self.format_cobol_level_and_name(level=level, name=name)

    def format_cobol_level_and_name(
        self,
        level,
        name: str,
    ) -> str:
        level_text = self.to_string(level)

        if level_text:
            try:
                level_text = f"{int(level_text):02d}"
            except Exception:
                pass

        if level_text and name:
            return f"{level_text} {name}"

        if name:
            return str(name)

        return level_text

    def remove_record_suffix(
        self,
        name: str,
    ) -> str:
        value = str(name or "").strip().upper()
        value = re.sub(r"[_\-\s]+[0-9]{4}$", "", value)
        value = re.sub(r"[0-9]{4}$", "", value)
        value = re.sub(r"[_\-\s]+$", "", value)

        return value

    def to_db2_name(
        self,
        value: str,
    ) -> str:
        normalized = str(value or "").upper().strip()
        normalized = re.sub(r"[^A-Z0-9]+", "_", normalized)
        normalized = re.sub(r"_+", "_", normalized)
        normalized = normalized.strip("_")

        return normalized

    def name_parts(
        self,
        value: str,
    ) -> list[str]:
        normalized = self.to_db2_name(value or "")

        return [part for part in normalized.split("_") if part]

    def empty_row(
        self,
    ) -> dict[str, str]:
        return {column: "" for column in self.COLUMNS}

    def to_string(
        self,
        value,
    ) -> str:
        if value is None:
            return ""

        return str(value)

    def safe_int(
        self,
        value,
        default: int = 0,
    ) -> int:
        try:
            if value is None:
                return default

            text = str(value).strip()

            if not text:
                return default

            return int(text)
        except Exception:
            return default