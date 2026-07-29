import re

from idms_modernizer.domain.db2_models import (
    DB2Model,
    DB2Table,
    DB2Column,
)
from idms_modernizer.domain.schema_models import SchemaMetadata
from idms_modernizer.services.name_normalizer import NameNormalizer
from idms_modernizer.services.db2_datatype_mapper import DB2DatatypeMapper


print("LOADED ExcelSheetMappingService VERSION PIC-MANUAL-PARSER-FIX-2026-07-29")


class ExcelSheetMappingService:
    """
    Builds Excel Sheet Mapping rows.

    Critical rule:
    New DB2 Data Type is always calculated from IDMS PIC Clause when PIC exists.

    Required mapping:
    - PIC X(n) -> CHAR(n)
    - PIC 9(n) -> DECIMAL(n)
    - PIC 9(n) COMP-3 -> DECIMAL(n,0)
    - PIC S9(n) COMP-3 -> DECIMAL(n,0)
    - PIC S9(n)V9(m) COMP-3 -> DECIMAL(n+m,m)
    - DATE fields -> DATE
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

    def build(
        self,
        metadata: SchemaMetadata,
        db2_model: DB2Model,
    ) -> list[dict[str, str]]:
        print("USING ExcelSheetMappingService.build VERSION PIC-MANUAL-PARSER-FIX-2026-07-29")

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

        self.debug_bad_rows_after_force(
            rows=rows,
        )

        return rows

    def force_pic_based_datatypes(
        self,
        rows: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        print("USING force_pic_based_datatypes VERSION PIC-MANUAL-PARSER-FIX-2026-07-29")

        corrected_rows: list[dict[str, str]] = []

        total_pic_rows = 0
        total_corrected_rows = 0
        total_date_rows = 0
        total_unmapped_pic_rows = 0
        total_skipped_blank_db2_target = 0

        for index, row in enumerate(rows or []):
            pic_clause = str(row.get("IDMS PIC Clause", "") or "").strip()
            current_db2_type = str(row.get("New DB2 Data Type", "") or "").strip()
            basetype = str(row.get("Basetype", "") or "").strip().upper()
            cobol_zone = str(row.get("Cobol Zone", "") or "").strip()
            db2_field_name = str(row.get("New DB2 Field name", "") or "").strip()
            new_db2_record = str(row.get("New DB2 Record", "") or "").strip()

            if not pic_clause:
                corrected_rows.append(row)
                continue

            total_pic_rows += 1

            if basetype == "DATE" or current_db2_type.upper() == "DATE":
                row["New DB2 Data Type"] = "DATE"
                total_date_rows += 1
                corrected_rows.append(row)
                continue

            if not new_db2_record or not db2_field_name:
                total_skipped_blank_db2_target += 1
                corrected_rows.append(row)
                continue

            mapped_type = self.map_idms_pic_to_db2_datatype(
                pic_clause=pic_clause,
                cobol_zone=cobol_zone,
                basetype=basetype,
            )

            if mapped_type:
                row["New DB2 Data Type"] = mapped_type
                total_corrected_rows += 1
            else:
                total_unmapped_pic_rows += 1

            corrected_rows.append(row)

        print(
            "PIC_DEBUG_SUMMARY "
            f"total_rows={len(rows or [])} "
            f"total_pic_rows={total_pic_rows} "
            f"total_corrected_rows={total_corrected_rows} "
            f"total_date_rows={total_date_rows} "
            f"total_skipped_blank_db2_target={total_skipped_blank_db2_target} "
            f"total_unmapped_pic_rows={total_unmapped_pic_rows}"
        )

        return corrected_rows

    def debug_bad_rows_after_force(
        self,
        rows: list[dict[str, str]],
    ) -> None:
        bad_rows = []

        for row in rows or []:
            pic_clause = str(row.get("IDMS PIC Clause", "") or "").strip()
            db2_type = str(row.get("New DB2 Data Type", "") or "").strip()
            db2_record = str(row.get("New DB2 Record", "") or "").strip()
            db2_field = str(row.get("New DB2 Field name", "") or "").strip()
            basetype = str(row.get("Basetype", "") or "").strip().upper()
            cobol_zone = str(row.get("Cobol Zone", "") or "")

            if not pic_clause:
                continue

            if not db2_record or not db2_field:
                continue

            if basetype == "DATE" or db2_type.upper() == "DATE":
                continue

            expected = self.map_idms_pic_to_db2_datatype(
                pic_clause=pic_clause,
                cobol_zone=cobol_zone,
                basetype=basetype,
            )

            if expected and expected != db2_type:
                bad_rows.append(
                    {
                        "Cobol Zone": row.get("Cobol Zone", ""),
                        "PIC": pic_clause,
                        "Expected": expected,
                        "Actual": db2_type,
                    }
                )

        print(f"PIC_DEBUG_AFTER_FORCE_BAD_ROWS_COUNT={len(bad_rows)}")

        for bad_row in bad_rows[:100]:
            print(f"PIC_DEBUG_BAD_ROW {bad_row}")

    def map_idms_pic_to_db2_datatype(
        self,
        pic_clause: str,
        cobol_zone: str = "",
        basetype: str = "",
    ) -> str:
        if not pic_clause:
            return ""

        if str(basetype or "").upper() == "DATE":
            return "DATE"

        if self.is_date_like_name(cobol_zone) and self.is_yyyymmdd_picture(pic_clause):
            return "DATE"

        clean = self.clean_pic_clause(
            pic_clause=pic_clause,
        )

        if not clean:
            return ""

        has_comp3 = "COMP-3" in clean
        has_comp = bool(re.search(r"\bCOMP\b", clean)) and not has_comp3

        core = clean
        core = core.replace("COMP-3", "")
        core = re.sub(r"\bCOMP\b", "", core)
        core = core.replace("DISPLAY", "")
        core = core.replace("USAGE", "")
        core = core.replace("IS", "")
        core = re.sub(r"\s+", "", core)

        if self.is_x_picture(core):
            length = self.character_length_from_core(
                core=core,
            )

            if length > 0:
                return f"CHAR({length})"

        if "V" in core and "9" in core:
            precision, scale = self.precision_scale_from_picture_core(
                core=core,
            )
            return f"DECIMAL({precision},{scale})"

        if "9" in core:
            precision = self.precision_from_picture_core(
                core=core,
            )

            if has_comp3 or has_comp:
                return f"DECIMAL({precision},0)"

            return f"DECIMAL({precision})"

        return ""

    def clean_pic_clause(
        self,
        pic_clause: str,
    ) -> str:
        text = str(pic_clause or "").strip().upper()

        text = text.replace("PICTURE", "")
        text = text.replace("PIC", "")
        text = text.replace(".", "")
        text = text.replace("\u00a0", " ")
        text = text.replace("\t", " ")

        text = re.sub(r"\s+", " ", text).strip()

        text = text.replace(" (", "(")
        text = text.replace("( ", "(")
        text = text.replace(" )", ")")
        text = text.replace(") ", ") ")

        text = re.sub(r"\s+", " ", text).strip()

        return text

    def is_x_picture(
        self,
        core: str,
    ) -> bool:
        text = str(core or "").strip().upper()

        if text.startswith("X(") and text.endswith(")"):
            return self.extract_parenthesized_int(text) is not None

        if text and set(text) == {"X"}:
            return True

        return False

    def character_length_from_core(
        self,
        core: str,
    ) -> int:
        text = str(core or "").strip().upper()

        if text.startswith("X(") and text.endswith(")"):
            parsed_length = self.extract_parenthesized_int(text)

            if parsed_length is not None:
                return parsed_length

        if text and set(text) == {"X"}:
            return len(text)

        return 0

    def precision_scale_from_picture_core(
        self,
        core: str,
    ) -> tuple[int, int]:
        text = str(core or "").strip().upper()

        if text.startswith("S"):
            text = text[1:]

        if "V" not in text:
            precision = self.precision_from_picture_core(
                core=text,
            )
            return precision, 0

        before_v, after_v = text.split("V", 1)

        integer_digits = self.count_9_digits(
            value=before_v,
        )
        decimal_digits = self.count_9_digits(
            value=after_v,
        )

        return integer_digits + decimal_digits, decimal_digits

    def precision_from_picture_core(
        self,
        core: str,
    ) -> int:
        text = str(core or "").strip().upper()

        if text.startswith("S"):
            text = text[1:]

        if "V" in text:
            before_v, after_v = text.split("V", 1)

            return self.count_9_digits(
                value=before_v,
            ) + self.count_9_digits(
                value=after_v,
            )

        return self.count_9_digits(
            value=text,
        )

    def count_9_digits(
        self,
        value: str,
    ) -> int:
        text = str(value or "").strip().upper()

        if text.startswith("S"):
            text = text[1:]

        total = 0
        index = 0

        while index < len(text):
            char = text[index]

            if char != "9":
                index += 1
                continue

            if index + 1 < len(text) and text[index + 1] == "(":
                close_index = text.find(")", index + 2)

                if close_index != -1:
                    number_text = text[index + 2:close_index].strip()

                    if number_text.isdigit():
                        total += int(number_text)
                        index = close_index + 1
                        continue

            total += 1
            index += 1

        return total

    def extract_parenthesized_int(
        self,
        value: str,
    ) -> int | None:
        text = str(value or "").strip()

        open_index = text.find("(")

        if open_index == -1:
            return None

        close_index = text.find(")", open_index + 1)

        if close_index == -1:
            return None

        number_text = text[open_index + 1:close_index].strip()

        if not number_text.isdigit():
            return None

        return int(number_text)

    def is_yyyymmdd_picture(
        self,
        pic_clause: str,
    ) -> bool:
        clean = self.clean_pic_clause(
            pic_clause=pic_clause,
        )

        core = clean
        core = core.replace("COMP-3", "")
        core = re.sub(r"\bCOMP\b", "", core)
        core = core.replace("DISPLAY", "")
        core = re.sub(r"\s+", "", core)

        return core in {
            "9(8)",
            "S9(8)",
            "99999999",
            "S99999999",
        }

    def is_date_like_name(
        self,
        value: str,
    ) -> bool:
        text = self.to_db2_name(value or "")
        parts = [
            part
            for part in text.split("_")
            if part
        ]

        if any(part in self.DATE_TOKENS for part in parts):
            return True

        compact = "".join(parts)

        return any(token in compact for token in self.DATE_TOKENS)

    def build_table_lookup(
        self,
        db2_model: DB2Model,
    ) -> dict[str, DB2Table]:
        lookup: dict[str, DB2Table] = {}

        for table in getattr(db2_model, "tables", []) or []:
            table_name = getattr(table, "name", "") or ""
            normalized = NameNormalizer.normalize(table_name)

            if normalized:
                lookup[normalized] = table
                lookup[self.remove_record_suffix(normalized)] = table

        return lookup

    def build_relationship_lookup(
        self,
        metadata: SchemaMetadata,
    ) -> dict[str, str]:
        lookup: dict[str, str] = {}

        for relationship in getattr(metadata, "relationships", []) or []:
            set_name = self.get_relationship_set_name(
                relationship=relationship,
            )
            owner_record = self.get_relationship_owner_record(
                relationship=relationship,
            )
            member_record = self.get_relationship_member_record(
                relationship=relationship,
            )

            if owner_record and set_name:
                lookup[NameNormalizer.normalize(owner_record)] = set_name

            if member_record and set_name:
                lookup[NameNormalizer.normalize(member_record)] = set_name

        return lookup

    def has_level_01_row(
        self,
        record,
        mapping_fields,
    ) -> bool:
        record_name = NameNormalizer.normalize(
            getattr(record, "name", "") or "",
        )

        for field in mapping_fields or []:
            level = getattr(field, "level", None)

            try:
                if int(level) != 1:
                    continue
            except Exception:
                continue

            field_name = NameNormalizer.normalize(
                getattr(field, "name", "") or "",
            )

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
        row["Cobol Zone"] = self.format_cobol_level_and_name(
            level=1,
            name=record_name,
        )

        return row

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

            is_direct_date = self.is_date_field(
                field=field,
            )

            is_date = (
                is_outer_date
                or is_date_child
                or is_direct_date
            )

            calc_status = calc_scope.get(
                id(field),
                "",
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

            if calc_status == "DESCENDANT" and not is_date:
                db2_key = self.add_pk_to_db2_key(
                    db2_key=db2_key,
                )

            if is_date:
                db2_key = ""

            row = self.empty_row()

            pic_clause = self.get_field_picture(field=field)

            row["Cobol Record IDMS"] = getattr(record, "name", "") or ""
            row["Cobol Zone"] = self.format_cobol_zone(field=field)
            row["IDMS Key"] = self.idms_key_label(
                calc_status=calc_status,
                is_date=is_date,
                db2_key=db2_key,
            )
            row["IDMS PIC Clause"] = pic_clause
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

            elif is_group:
                row["New DB2 Record"] = ""
                row["New DB2 Field name"] = ""
                row["New DB2 Data Type"] = ""

            elif self.should_emit_db2_field(field=field):
                row["New DB2 Record"] = self.db2_record_name(
                    record=record,
                    table=table,
                )
                row["New DB2 Field name"] = self.convert_cobol_zone_to_db2_field_name(
                    record=record,
                    field=field,
                )

                if pic_clause:
                    row["New DB2 Data Type"] = self.map_idms_pic_to_db2_datatype(
                        pic_clause=pic_clause,
                        cobol_zone=row["Cobol Zone"],
                        basetype=self.get_field_basetype(field=field),
                    )
                else:
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

    def build_column_lookup(
        self,
        table: DB2Table | None,
    ) -> dict[str, DB2Column]:
        lookup: dict[str, DB2Column] = {}

        if table is None:
            return lookup

        for column in getattr(table, "columns", []) or []:
            column_name = getattr(column, "name", "") or ""
            normalized = NameNormalizer.normalize(column_name)

            if normalized:
                lookup[normalized] = column
                lookup[self.remove_record_suffix(normalized)] = column

        return lookup

    def build_date_scope(
        self,
        fields,
    ) -> dict[int, bool]:
        scope: dict[int, bool] = {}
        active_date_levels: list[int] = []

        for field in fields or []:
            level = self.safe_int(
                getattr(field, "level", None),
                default=0,
            )

            active_date_levels = [
                current_level
                for current_level in active_date_levels
                if current_level < level
            ]

            if active_date_levels:
                scope[id(field)] = True

            if self.is_potential_date_group(field=field):
                active_date_levels.append(level)

        return scope

    def collect_date_group_info(
        self,
        fields,
    ) -> dict[str, dict]:
        info: dict[str, dict] = {}

        for field in fields or []:
            if not self.is_group_field(field=field):
                continue

            if not self.is_potential_date_group(field=field):
                continue

            field_name = NameNormalizer.normalize(
                getattr(field, "name", "") or "",
            )

            if not field_name:
                continue

            info[field_name] = {
                "field": field,
                "db2_field_name": self.to_db2_name(
                    self.remove_record_suffix(field_name),
                ),
            }

        return info

    def build_calc_scope(
        self,
        record,
        fields,
    ) -> dict[int, str]:
        scope: dict[int, str] = {}
        active_calc_levels: list[int] = []

        for field in fields or []:
            level = self.safe_int(
                getattr(field, "level", None),
                default=0,
            )
            field_name = NameNormalizer.normalize(
                getattr(field, "name", "") or "",
            )

            active_calc_levels = [
                current_level
                for current_level in active_calc_levels
                if current_level < level
            ]

            if self.is_calc_field_name(field_name=field_name):
                scope[id(field)] = "ROOT"
                active_calc_levels.append(level)
                continue

            if active_calc_levels:
                scope[id(field)] = "DESCENDANT"

        return scope

    def is_calc_field_name(
        self,
        field_name: str,
    ) -> bool:
        parts = self.name_parts(field_name or "")

        return "CALC" in parts

    def is_outer_date_group(
        self,
        field,
        date_group_info: dict[str, dict],
    ) -> bool:
        if not self.is_group_field(field=field):
            return False

        field_name = NameNormalizer.normalize(
            getattr(field, "name", "") or "",
        )

        return field_name in date_group_info

    def is_date_child(
        self,
        field,
        date_scope: dict[int, bool],
    ) -> bool:
        if id(field) not in date_scope:
            return False

        return self.is_date_part_name(
            field_name=getattr(field, "name", "") or "",
        )

    def is_potential_date_group(
        self,
        field,
    ) -> bool:
        if self.is_date_field(field=field):
            return True

        return self.is_date_like_name(
            getattr(field, "name", "") or "",
        )

    def is_date_field(
        self,
        field,
    ) -> bool:
        datatype = str(
            getattr(field, "datatype", None)
            or getattr(field, "data_type", None)
            or getattr(field, "type", None)
            or "",
        ).strip().upper()

        if datatype == "DATE":
            return True

        field_name = getattr(field, "name", "") or ""
        pic_clause = self.get_field_picture(field=field)

        if self.is_date_like_name(field_name) and self.is_yyyymmdd_picture(pic_clause):
            return True

        return False

    def is_date_part_name(
        self,
        field_name: str,
    ) -> bool:
        parts = self.name_parts(field_name or "")

        for part in parts:
            if part in self.YEAR_PARTS:
                return True
            if part in self.MONTH_PARTS:
                return True
            if part in self.DAY_PARTS:
                return True

        return False

    def find_table_for_record(
        self,
        record_name: str,
        table_lookup: dict[str, DB2Table],
    ) -> DB2Table | None:
        normalized_record_name = NameNormalizer.normalize(record_name or "")

        if normalized_record_name in table_lookup:
            return table_lookup[normalized_record_name]

        without_suffix = self.remove_record_suffix(
            normalized_record_name,
        )

        if without_suffix in table_lookup:
            return table_lookup[without_suffix]

        for table_name, table in table_lookup.items():
            if self.remove_record_suffix(table_name) == without_suffix:
                return table

        return None

    def find_matching_column(
        self,
        normalized_column_name: str,
        column_lookup: dict[str, DB2Column],
    ) -> DB2Column | None:
        normalized_column_name = NameNormalizer.normalize(
            normalized_column_name or "",
        )

        if normalized_column_name in column_lookup:
            return column_lookup[normalized_column_name]

        without_suffix = self.remove_record_suffix(
            normalized_column_name,
        )

        if without_suffix in column_lookup:
            return column_lookup[without_suffix]

        for current_name, column in column_lookup.items():
            if self.remove_record_suffix(current_name) == without_suffix:
                return column

        return None

    def find_column_for_field(
        self,
        record,
        field,
        column_lookup: dict[str, DB2Column],
    ) -> DB2Column | None:
        field_name = NameNormalizer.normalize(
            getattr(field, "name", "") or "",
        )

        if not field_name:
            return None

        possible_names = [
            field_name,
            self.remove_record_suffix(field_name),
            self.convert_cobol_zone_to_db2_field_name(
                record=record,
                field=field,
            ),
            self.convert_date_field_to_db2_field_name(
                record=record,
                field=field,
            ),
        ]

        for name in possible_names:
            column = self.find_matching_column(
                normalized_column_name=name,
                column_lookup=column_lookup,
            )

            if column is not None:
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
        row["Length of Field Bytes"] = self.to_string(
            self.get_field_length(field=field)
        )
        row["Field end position"] = self.to_string(
            self.get_field_end_position(field=field)
        )

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
            row["New DB2 Data Type"] = self.get_db2_datatype(
                db2_column=column,
            )
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

        column_lookup = {
            NameNormalizer.normalize(getattr(column, "name", "") or ""): column
            for column in getattr(table, "columns", []) or []
        }

        for foreign_key in getattr(table, "foreign_keys", []) or []:
            fk_column_name = self.get_foreign_key_column_name(
                foreign_key=foreign_key,
            )

            if not fk_column_name:
                continue

            fk_column = column_lookup.get(
                NameNormalizer.normalize(fk_column_name),
            )

            if fk_column is None:
                continue

            set_name = getattr(foreign_key, "set_name", "") or ""

            fk_datatype = self.get_db2_datatype(
                db2_column=fk_column,
            )

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
        normalized_current_table = NameNormalizer.normalize(
            getattr(member_table, "name", "") or "",
        )

        for relationship in getattr(metadata, "relationships", []) or []:
            set_name = self.get_relationship_set_name(
                relationship=relationship,
            )
            owner_record_name = self.get_relationship_owner_record(
                relationship=relationship,
            )
            member_record_name = self.get_relationship_member_record(
                relationship=relationship,
            )

            if not set_name:
                continue

            normalized_member_record = NameNormalizer.normalize(
                member_record_name,
            )

            if normalized_member_record not in {
                normalized_current_record,
                normalized_current_table,
            }:
                continue

            owner_table = self.find_table_for_record(
                record_name=owner_record_name,
                table_lookup=table_lookup,
            )

            owner_pk_column = self.find_primary_key_column(
                table=owner_table,
            )

            if owner_pk_column is None:
                continue

            fk_column = self.find_existing_fk_column_for_set(
                member_table=member_table,
                set_name=set_name,
                owner_pk_column=owner_pk_column,
            )

            if fk_column is not None:
                fk_column_name = getattr(fk_column, "name", "") or ""
                fk_datatype = self.get_db2_datatype(
                    db2_column=fk_column,
                )
            else:
                fk_column_name = self.generated_set_fk_column_name(
                    set_name=set_name,
                    owner_pk_column_name=getattr(owner_pk_column, "name", "") or "",
                )
                fk_datatype = self.get_db2_datatype(
                    db2_column=owner_pk_column,
                )

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

    def find_existing_fk_column_for_set(
        self,
        member_table: DB2Table,
        set_name: str,
        owner_pk_column: DB2Column,
    ) -> DB2Column | None:
        owner_pk_name = NameNormalizer.normalize(
            getattr(owner_pk_column, "name", "") or "",
        )
        set_name_normalized = NameNormalizer.normalize(set_name or "")

        for column in getattr(member_table, "columns", []) or []:
            column_name = NameNormalizer.normalize(
                getattr(column, "name", "") or "",
            )

            source_kind = str(
                getattr(column, "source_kind", "") or "",
            ).upper()

            if source_kind in {"FK", "FOREIGN KEY", "SET FK"}:
                return column

            if owner_pk_name and owner_pk_name in column_name:
                return column

            if set_name_normalized and set_name_normalized in column_name:
                return column

        return None

    def find_primary_key_column(
        self,
        table: DB2Table | None,
    ) -> DB2Column | None:
        if table is None:
            return None

        primary_keys = list(getattr(table, "primary_keys", []) or [])

        primary_key = getattr(table, "primary_key", None)

        if primary_key:
            primary_keys.append(primary_key)

        normalized_primary_keys = {
            NameNormalizer.normalize(primary_key)
            for primary_key in primary_keys
            if primary_key
        }

        for column in getattr(table, "columns", []) or []:
            column_name = NameNormalizer.normalize(
                getattr(column, "name", "") or "",
            )

            if column_name in normalized_primary_keys:
                return column

            db2_key = str(getattr(column, "key", "") or "").upper()

            if db2_key == "PK":
                return column

        columns = list(getattr(table, "columns", []) or [])

        return columns[0] if columns else None

    def generated_set_fk_column_name(
        self,
        set_name: str,
        owner_pk_column_name: str,
    ) -> str:
        set_base = self.to_db2_name(set_name or "SET")
        pk_base = self.to_db2_name(owner_pk_column_name or "ID")

        return f"FK_{set_base}_{pk_base}"

    def get_foreign_key_column_name(
        self,
        foreign_key,
    ) -> str:
        return str(
            getattr(foreign_key, "column", None)
            or getattr(foreign_key, "column_name", None)
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

    def infer_db2_datatype_from_field(
        self,
        field,
    ) -> str:
        pic_clause = self.get_field_picture(
            field=field,
        )

        if pic_clause:
            return self.map_idms_pic_to_db2_datatype(
                pic_clause=pic_clause,
                cobol_zone=self.format_cobol_zone(field=field),
                basetype=self.get_field_basetype(field=field),
            )

        datatype = str(
            getattr(field, "datatype", "") or "",
        ).upper()

        if datatype == "DATE":
            return "DATE"

        if datatype in {"TIMESTAMP", "DATETIME"}:
            return "TIMESTAMP"

        length = (
            getattr(field, "length", None)
            or getattr(field, "storage_length", None)
            or getattr(field, "physical_length", None)
            or 1
        )

        if datatype in {"CHAR", "VARCHAR", "DISPLAY", "TEXT"}:
            return f"CHAR({int(length)})"

        if datatype in {"DECIMAL", "NUMERIC"}:
            scale = getattr(field, "scale", None)

            if scale is not None and int(scale) > 0:
                return f"DECIMAL({int(length)},{int(scale)})"

            return f"DECIMAL({int(length)})"

        return ""

    def get_db2_datatype(
        self,
        db2_column: DB2Column | None,
    ) -> str:
        if db2_column is None:
            return ""

        datatype = str(
            getattr(db2_column, "datatype", None)
            or getattr(db2_column, "data_type", None)
            or getattr(db2_column, "type", None)
            or "",
        ).strip().upper()

        length = (
            getattr(db2_column, "length", None)
            or getattr(db2_column, "precision", None)
        )
        scale = getattr(db2_column, "scale", None)

        if not datatype:
            return ""

        if datatype == "DATE":
            return "DATE"

        if datatype in {"TIMESTAMP", "DATETIME"}:
            return "TIMESTAMP"

        if datatype in {"CHAR", "VARCHAR"}:
            if length:
                return f"CHAR({length})"
            return "CHAR(1)"

        if datatype in {"DECIMAL", "NUMERIC"}:
            if length and scale is not None:
                return f"DECIMAL({length},{scale})"

            if length:
                return f"DECIMAL({length})"

            return "DECIMAL(18)"

        return datatype

    def db2_key_label(
        self,
        table: DB2Table | None,
        column: DB2Column | None,
    ) -> str:
        if table is None or column is None:
            return ""

        column_name = NameNormalizer.normalize(
            getattr(column, "name", "") or "",
        )

        primary_keys = list(getattr(table, "primary_keys", []) or [])

        primary_key = getattr(table, "primary_key", None)

        if primary_key:
            primary_keys.append(primary_key)

        normalized_primary_keys = {
            NameNormalizer.normalize(primary_key)
            for primary_key in primary_keys
            if primary_key
        }

        if column_name in normalized_primary_keys:
            return "PK"

        key_value = str(
            getattr(column, "key", "") or "",
        ).upper()

        if key_value in {"PK", "FK"}:
            return key_value

        source_kind = str(
            getattr(column, "source_kind", "") or "",
        ).upper()

        if source_kind in {"GENERATED PK", "PK"}:
            return "PK"

        if source_kind in {"FK", "FOREIGN KEY", "SET FK"}:
            return "FK"

        return ""

    def add_pk_to_db2_key(
        self,
        db2_key: str,
    ) -> str:
        parts = [
            part.strip()
            for part in str(db2_key or "").split("/")
            if part.strip()
        ]

        if "PK" not in parts:
            parts.append("PK")

        return "/".join(parts)

    def idms_key_label(
        self,
        calc_status: str,
        is_date: bool,
        db2_key: str,
    ) -> str:
        if is_date:
            return ""

        labels: list[str] = []

        if calc_status == "DESCENDANT":
            labels.append("CALC")

        for part in str(db2_key or "").split("/"):
            clean = part.strip()

            if not clean:
                continue

            if clean == "PK":
                labels.append("CALC")

            if clean == "FK":
                labels.append("SET")

        output: list[str] = []

        for label in labels:
            if label not in output:
                output.append(label)

        return "; ".join(output)

    def should_emit_db2_field(
        self,
        field,
    ) -> bool:
        if self.is_filler_field(field=field):
            return False

        if self.is_date_field(field=field):
            return False

        if self.is_group_field(field=field):
            return False

        picture = self.get_field_picture(field=field)

        if picture:
            return True

        datatype = str(
            getattr(field, "datatype", "") or "",
        ).upper()

        if datatype in {"CHAR", "VARCHAR", "DECIMAL", "NUMERIC"}:
            return True

        return False

    def is_filler_field(
        self,
        field,
    ) -> bool:
        return NameNormalizer.normalize(
            getattr(field, "name", "") or "",
        ) == "FILLER"

    def is_group_field(
        self,
        field,
    ) -> bool:
        return bool(
            getattr(field, "has_child", False)
            or getattr(field, "is_group", False)
        )

    def db2_record_name(
        self,
        record,
        table: DB2Table | None,
    ) -> str:
        if table is not None and getattr(table, "name", None):
            return getattr(table, "name", "") or ""

        return self.to_db2_name(
            getattr(record, "name", "") or "",
        )

    def convert_cobol_zone_to_db2_field_name(
        self,
        record,
        field,
    ) -> str:
        field_name = getattr(field, "name", "") or ""

        return self.cobol_field_base_name(
            field_name=field_name,
        )

    def convert_date_field_to_db2_field_name(
        self,
        record,
        field,
    ) -> str:
        field_name = getattr(field, "name", "") or ""

        return self.date_field_base_name(
            field_name=field_name,
        )

    def cobol_field_base_name(
        self,
        field_name: str,
    ) -> str:
        normalized = self.to_db2_name(field_name)

        normalized = re.sub(
            r"_[0-9]{4}$",
            "",
            normalized,
        )

        return normalized

    def date_field_base_name(
        self,
        field_name: str,
    ) -> str:
        normalized = self.to_db2_name(field_name)

        normalized = re.sub(
            r"_[0-9]{4}$",
            "",
            normalized,
        )

        return normalized

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
        normalized = NameNormalizer.normalize(value or "")
        normalized = str(normalized or "").upper()
        normalized = re.sub(r"[^A-Z0-9]+", "_", normalized)
        normalized = re.sub(r"_+", "_", normalized)
        normalized = normalized.strip("_")

        return normalized

    def name_parts(
        self,
        value: str,
    ) -> list[str]:
        normalized = self.to_db2_name(value or "")

        return [
            part
            for part in normalized.split("_")
            if part
        ]

    def format_cobol_zone(
        self,
        field,
    ) -> str:
        level = getattr(field, "level", None)
        name = getattr(field, "name", "") or ""

        return self.format_cobol_level_and_name(
            level=level,
            name=name,
        )

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

    def get_field_picture(
        self,
        field,
    ) -> str:
        text = str(
            getattr(field, "picture", None)
            or getattr(field, "pic", None)
            or getattr(field, "pic_clause", None)
            or "",
        ).strip()

        if text.upper().startswith("PIC "):
            text = text[4:].strip()

        if text.upper().startswith("PICTURE "):
            text = text[8:].strip()

        return text

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
        end_position = (
            getattr(field, "end_position", None)
            or getattr(field, "field_end_position", None)
            or getattr(field, "end", None)
        )

        if end_position is not None:
            return end_position

        start = (
            getattr(field, "start_position", None)
            or getattr(field, "start", None)
        )

        length = self.get_field_length(field=field)

        try:
            if start is not None and length not in ("", None):
                return int(start) + int(length) - 1
        except Exception:
            return ""

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

    def empty_row(
        self,
    ) -> dict[str, str]:
        return {
            column: ""
            for column in self.COLUMNS
        }

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