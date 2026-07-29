import re

from idms_modernizer.domain.db2_models import (
    DB2Model,
    DB2Table,
    DB2Column,
)
from idms_modernizer.domain.schema_models import SchemaMetadata
from idms_modernizer.services.name_normalizer import NameNormalizer


class ExcelSheetMappingService:
    """
    Builds Excel Sheet Mapping rows.

    Rules implemented:
    - Always add level 01 record row.
    - Include all outer/group rows from mapping_fields.
    - FILLER rows are COBOL-only.
    - Outer CALC group does not show CALC.
    - Inner descendants of CALC group show CALC.
    - Inner non-date descendants of CALC group show PK.
    - Date groups/date parts do not show CALC or PK.
    - Date outer group maps to DB2 DATE and gets generated date DB2 field name.
    - Date child parts remain visible but DB2 mapping stays blank.
    - Elementary non-date fields get generated DB2 field name:
      <normalized COBOL field base>_479<record suffix>.
    - SET/FK rows:
      Cobol Record IDMS = COBOL record name
      IDMS Key = SET
      DB2 Key = FK
      Relation = SET name
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

    YEAR_PARTS = {"YEAR", "YR", "Y", "YY", "YYYY", "DY"}
    MONTH_PARTS = {"MONTH", "MON", "MO", "M", "MM", "DM"}
    DAY_PARTS = {"DAY", "D", "DD"}

    def build(
        self,
        metadata: SchemaMetadata,
        db2_model: DB2Model,
    ) -> list[dict[str, str]]:
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

        return rows

    def has_level_01_row(
        self,
        record,
        mapping_fields,
    ) -> bool:
        record_name = NameNormalizer.normalize(
            getattr(record, "name", "") or ""
        )

        for field in mapping_fields or []:
            level = getattr(field, "level", None)

            try:
                if int(level) != 1:
                    continue
            except Exception:
                continue

            field_name = NameNormalizer.normalize(
                getattr(field, "name", "") or ""
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

        column_lookup = self.build_column_lookup(
            table=table,
        ) if table else {}

        group_scope = self.build_group_scope(
            fields=mapping_fields,
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

            field_name = NameNormalizer.normalize(
                getattr(field, "name", "") or ""
            )

            is_group = field_name in group_scope

            is_date_child = self.is_date_part_name(
                field_name=field_name,
            )

            is_outer_date = (
                self.is_actual_outer_date_field(
                    field=field,
                    date_group_info=date_group_info,
                )
                or date_scope.get(field_name) == "DATE_GROUP"
            )

            is_date = (
                is_outer_date
                or is_date_child
                or self.is_date_field(field=field)
                or field_name in date_scope
            )

            calc_status = self.calc_status_for_field(
                field=field,
                calc_scope=calc_scope,
            )

            db2_column = None

            if not is_group and not is_date_child:
                db2_column = self.find_column_for_field(
                    record=record,
                    field=field,
                    column_lookup=column_lookup,
                    date_group_info=date_group_info,
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

            row["Cobol Record IDMS"] = getattr(record, "name", "") or ""
            row["Cobol Zone"] = self.format_cobol_zone(field=field)
            row["IDMS Key"] = self.idms_key_label(
                calc_status=calc_status,
                is_date=is_date,
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
                row["New DB2 Record"] = self.db2_record_name(record=record, table=table)
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

            elif self.is_date_field(field=field):
                row["New DB2 Record"] = self.db2_record_name(record=record, table=table)
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
                row["New DB2 Record"] = self.db2_record_name(record=record, table=table)
                row["New DB2 Field name"] = self.convert_cobol_zone_to_db2_field_name(
                    record=record,
                    field=field,
                )
                row["New DB2 Data Type"] = (
                    self.get_db2_datatype(db2_column=db2_column)
                    if db2_column is not None
                    else self.infer_db2_datatype_from_field(field=field)
                )

            row["Hopex Expression TypeRemark"] = self.hopex_remark(field=field)
            row["Relation"] = relationship_lookup.get(
                NameNormalizer.normalize(getattr(record, "name", "") or ""),
                "",
            )
            row["Basetype"] = self.get_field_basetype(field=field)

            rows.append(row)

        return rows

    def db2_record_name(
        self,
        record,
        table: DB2Table | None,
    ) -> str:
        if table is not None and getattr(table, "name", None):
            return getattr(table, "name", "") or ""

        return self.to_db2_name(getattr(record, "name", "") or "")

    def should_emit_db2_field(
        self,
        field,
    ) -> bool:
        if self.is_filler_field(field=field):
            return False

        if self.is_date_field(field=field):
            return False

        picture = self.get_field_picture(field=field)

        if picture:
            return True

        datatype = str(getattr(field, "datatype", "") or "").upper()

        if datatype in {"CHAR", "VARCHAR", "DECIMAL", "NUMERIC"}:
            return True

        return False

    def convert_cobol_zone_to_db2_field_name(
        self,
        record,
        field,
    ) -> str:
        field_name = getattr(field, "name", "") or ""
        record_name = getattr(record, "name", "") or ""

        base_name = self.cobol_field_base_name(
            field_name=field_name,
        )

        record_code = self.record_code(
            record_name=record_name,
        )

        if record_code:
            return f"{base_name}_{record_code}"

        return base_name

    def convert_date_field_to_db2_field_name(
        self,
        record,
        field,
    ) -> str:
        field_name = getattr(field, "name", "") or ""
        record_name = getattr(record, "name", "") or ""

        base_name = self.date_field_base_name(
            field_name=field_name,
        )

        record_code = self.record_code(
            record_name=record_name,
        )

        if record_code:
            return f"{base_name}_{record_code}"

        return base_name

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

        parts = [
            part
            for part in normalized.split("_")
            if part
        ]

        if len(parts) >= 3:
            parts = parts[:-1]

        if not parts:
            return normalized

        return "_".join(parts)

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

        parts = [
            part
            for part in normalized.split("_")
            if part
        ]

        if not parts:
            return "DA_DATE"

        if parts[0] == "DA":
            if len(parts) == 1:
                return "DA_DATE"

            main_parts = parts[1:]

            if len(main_parts) >= 2:
                main_parts = main_parts[:-1]

            if not main_parts:
                return "DA_DATE"

            return "DA_" + "_".join(main_parts)

        if "DATE" in parts:
            parts = [
                part
                for part in parts
                if part != "DATE"
            ]

            if not parts:
                return "DA_DATE"

            return "DA_" + "_".join(parts)

        return normalized

    def record_code(
        self,
        record_name: str,
    ) -> str:
        normalized = self.to_db2_name(record_name)
        compact = re.sub(
            r"[^A-Z0-9]",
            "",
            normalized,
        )

        if not compact:
            return ""

        suffix = compact[-4:]

        return f"479{suffix}"

    def infer_db2_datatype_from_field(
        self,
        field,
    ) -> str:
        datatype = str(getattr(field, "datatype", "") or "").upper()
        length = getattr(field, "length", None)
        scale = getattr(field, "scale", None)
        picture = self.get_field_picture(field=field).upper()

        if datatype == "DATE":
            return "DATE"

        if "COMP-3" in picture:
            precision, decimal_scale = self.precision_scale_from_picture(picture=picture)
            return f"DECIMAL({precision},{decimal_scale})"

        if "V" in picture and "9" in picture:
            precision, decimal_scale = self.precision_scale_from_picture(picture=picture)
            return f"DECIMAL({precision},{decimal_scale})"

        if "9" in picture:
            precision, _ = self.precision_scale_from_picture(picture=picture)
            return f"DECIMAL({precision})"

        if "X" in picture:
            actual_length = self.safe_int(
                value=length,
                default=self.character_length_from_picture(picture=picture),
            )

            if actual_length == 100:
                return "VARCHAR(100)"

            return f"CHAR({actual_length})"

        if datatype in {"DECIMAL", "NUMERIC"}:
            actual_length = self.safe_int(value=length, default=18)
            actual_scale = self.safe_int(value=scale, default=0)

            if actual_scale > 0:
                return f"DECIMAL({actual_length},{actual_scale})"

            return f"DECIMAL({actual_length})"

        if datatype in {"CHAR", "VARCHAR"}:
            actual_length = self.safe_int(value=length, default=1)

            if actual_length == 100:
                return "VARCHAR(100)"

            return f"CHAR({actual_length})"

        return "CHAR(1)"

    def precision_scale_from_picture(
        self,
        picture: str,
    ) -> tuple[int, int]:
        text = str(picture or "").upper()
        text = text.replace("PIC", "")
        text = text.replace("PICTURE", "")
        text = text.replace("COMP-3", "")
        text = text.replace("COMP", "")
        text = text.replace("DISPLAY", "")
        text = text.replace(" ", "")
        text = text.replace(".", "")

        if "V" in text:
            before_v, after_v = text.split("V", 1)
            integer_digits = self.count_9_digits(before_v)
            decimal_digits = self.count_9_digits(after_v)
            return integer_digits + decimal_digits, decimal_digits

        return self.count_9_digits(text), 0

    def count_9_digits(
        self,
        value: str,
    ) -> int:
        total = 0

        for match in re.finditer(
            r"9(?:$(\d+)$)?",
            value,
            flags=re.IGNORECASE,
        ):
            if match.group(1):
                total += int(match.group(1))
            else:
                total += 1

        return total if total > 0 else 1

    def character_length_from_picture(
        self,
        picture: str,
    ) -> int:
        text = str(picture or "").upper()
        match = re.search(
            r"X$(\d+)$",
            text,
            flags=re.IGNORECASE,
        )

        if match:
            return int(match.group(1))

        count = text.count("X")
        return count if count > 0 else 1

    def safe_int(
        self,
        value,
        default: int,
    ) -> int:
        try:
            if value is None:
                return default
            return int(value)
        except Exception:
            return default

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

        ordered_parts = []

        if "PK" in parts:
            ordered_parts.append("PK")

        if "FK" in parts:
            ordered_parts.append("FK")

        return "/".join(ordered_parts)

    def build_group_scope(
        self,
        fields,
    ) -> dict[str, bool]:
        group_scope: dict[str, bool] = {}
        field_list = list(fields or [])

        for index, field in enumerate(field_list):
            field_name = NameNormalizer.normalize(
                getattr(field, "name", "") or ""
            )
            field_level = getattr(field, "level", None)

            if not field_name or field_level is None:
                continue

            try:
                field_level_int = int(field_level)
            except Exception:
                continue

            for next_field in field_list[index + 1:]:
                next_level = getattr(next_field, "level", None)

                if next_level is None:
                    continue

                try:
                    next_level_int = int(next_level)
                except Exception:
                    continue

                if next_level_int > field_level_int:
                    group_scope[field_name] = True
                    break

                if next_level_int <= field_level_int:
                    break

        return group_scope

    def build_date_scope(
        self,
        fields,
    ) -> dict[str, str]:
        date_scope: dict[str, str] = {}
        field_list = list(fields or [])

        for index, field in enumerate(field_list):
            field_name = NameNormalizer.normalize(
                getattr(field, "name", "") or ""
            )
            field_level = getattr(field, "level", None)

            if not field_name:
                continue

            if self.is_date_part_name(field_name=field_name):
                date_scope[field_name] = "DATE_PART"
                continue

            if self.is_date_field(field=field):
                date_scope[field_name] = "DATE_GROUP"
                continue

            if field_level is None:
                continue

            try:
                field_level_int = int(field_level)
            except Exception:
                continue

            descendants = []

            for next_field in field_list[index + 1:]:
                next_level = getattr(next_field, "level", None)

                if next_level is None:
                    continue

                try:
                    next_level_int = int(next_level)
                except Exception:
                    continue

                if next_level_int <= field_level_int:
                    break

                descendants.append(next_field)

            parts_found = set()

            for descendant in descendants:
                descendant_name = NameNormalizer.normalize(
                    getattr(descendant, "name", "") or ""
                )
                part = self.date_part_type_from_name(field_name=descendant_name)

                if part:
                    parts_found.add(part)

            if {"YEAR", "MONTH", "DAY"}.issubset(parts_found):
                date_scope[field_name] = "DATE_GROUP"

                for descendant in descendants:
                    descendant_name = NameNormalizer.normalize(
                        getattr(descendant, "name", "") or ""
                    )

                    if self.date_part_type_from_name(field_name=descendant_name):
                        date_scope[descendant_name] = "DATE_PART"

        return date_scope

    def date_part_type_from_name(
        self,
        field_name: str,
    ) -> str | None:
        tokens = self.split_name_tokens(field_name)

        for token in tokens:
            part = self.date_part_type(token=token, tokens=tokens)

            if part:
                return part

        return None

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
        mapping_fields = list(fields or [])

        key_field = None
        key_index = None

        for index, field in enumerate(mapping_fields):
            field_name = NameNormalizer.normalize(
                getattr(field, "name", "") or ""
            )

            if field_name == normalized_primary_key:
                key_field = field
                key_index = index
                break

            if self.remove_record_suffix(field_name) == self.remove_record_suffix(
                normalized_primary_key
            ):
                key_field = field
                key_index = index
                break

        if key_field is None or key_index is None:
            scope[normalized_primary_key] = "ROOT"
            return scope

        key_name = NameNormalizer.normalize(
            getattr(key_field, "name", "") or ""
        )
        scope[key_name] = "ROOT"
        key_level = getattr(key_field, "level", None)

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
        db2_key: str,
    ) -> str:
        labels = []

        if calc_status == "DESCENDANT" and not is_date:
            labels.append("CALC")

        if "FK" in [
            part.strip().upper()
            for part in str(db2_key or "").split("/")
            if part.strip()
        ]:
            labels.append("SET")

        return "; ".join(labels)

    def is_date_part_name(
        self,
        field_name: str,
    ) -> bool:
        return bool(
            self.parse_date_part_candidates(
                field_name=field_name,
            )
        )

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
            if getattr(column, "source_kind", "") != "GENERATED_PK":
                continue

            row = self.empty_row()
            row["Cobol Record IDMS"] = getattr(record, "name", "") or ""
            row["DB2 Key"] = "PK"
            row["New DB2 Record"] = getattr(table, "name", "") or ""
            row["New DB2 Field name"] = getattr(column, "name", "") or ""
            row["New DB2 Data Type"] = self.get_db2_datatype(
                db2_column=column
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
                foreign_key=foreign_key
            )
            if not fk_column_name:
                continue

            fk_column = column_lookup.get(NameNormalizer.normalize(fk_column_name))
            if fk_column is None:
                continue

            set_name = getattr(foreign_key, "set_name", "") or ""
            key = (
                NameNormalizer.normalize(cobol_record_name),
                NameNormalizer.normalize(getattr(table, "name", "") or ""),
                NameNormalizer.normalize(getattr(fk_column, "name", "") or ""),
                self.get_db2_datatype(db2_column=fk_column),
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
            row["New DB2 Data Type"] = self.get_db2_datatype(
                db2_column=fk_column
            )
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
            getattr(member_table, "name", "") or ""
        )

        for relationship in getattr(metadata, "relationships", []) or []:
            set_name = self.get_relationship_set_name(relationship=relationship)
            owner_record_name = self.get_relationship_owner_record(
                relationship=relationship
            )
            member_record_name = self.get_relationship_member_record(
                relationship=relationship
            )

            if not set_name or not owner_record_name or not member_record_name:
                continue

            normalized_member_record = NameNormalizer.normalize(member_record_name)
            is_current_member = (
                normalized_member_record == normalized_current_record
                or normalized_member_record == normalized_current_table
                or self.remove_record_suffix(normalized_member_record)
                == self.remove_record_suffix(normalized_current_record)
                or self.remove_record_suffix(normalized_member_record)
                == self.remove_record_suffix(normalized_current_table)
            )

            if not is_current_member:
                continue

            owner_table = self.find_table_for_record(
                record_name=owner_record_name,
                table_lookup=table_lookup,
            )

            if owner_table is None:
                continue

            owner_pk_columns = self.get_primary_key_columns(table=owner_table)
            if not owner_pk_columns:
                continue

            for owner_pk_column in owner_pk_columns:
                fk_column = self.find_existing_fk_column_for_set(
                    member_table=member_table,
                    set_name=set_name,
                    owner_pk_column=owner_pk_column,
                )

                if fk_column is not None:
                    fk_column_name = getattr(fk_column, "name", "") or ""
                    fk_datatype = self.get_db2_datatype(db2_column=fk_column)
                else:
                    fk_column_name = self.generated_set_fk_column_name(
                        set_name=set_name,
                        owner_pk_column_name=getattr(owner_pk_column, "name", "") or "",
                    )
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

    def find_existing_fk_column_for_set(
        self,
        member_table: DB2Table,
        set_name: str,
        owner_pk_column: DB2Column,
    ) -> DB2Column | None:
        expected_column_name = self.generated_set_fk_column_name(
            set_name=set_name,
            owner_pk_column_name=getattr(owner_pk_column, "name", "") or "",
        )

        for column in getattr(member_table, "columns", []) or []:
            column_name = getattr(column, "name", "") or ""
            if NameNormalizer.normalize(column_name) == NameNormalizer.normalize(
                expected_column_name
            ):
                return column

        for foreign_key in getattr(member_table, "foreign_keys", []) or []:
            fk_set_name = getattr(foreign_key, "set_name", "") or ""
            fk_column_name = self.get_foreign_key_column_name(
                foreign_key=foreign_key
            )

            if set_name and fk_set_name:
                if NameNormalizer.normalize(set_name) != NameNormalizer.normalize(
                    fk_set_name
                ):
                    continue

            for column in getattr(member_table, "columns", []) or []:
                if NameNormalizer.normalize(getattr(column, "name", "") or "") == NameNormalizer.normalize(
                    fk_column_name
                ):
                    return column

        return None

    def generated_set_fk_column_name(
        self,
        set_name: str,
        owner_pk_column_name: str,
    ) -> str:
        return self.to_db2_name(f"{set_name}_{owner_pk_column_name}")

    def get_primary_key_columns(
        self,
        table: DB2Table,
    ) -> list[DB2Column]:
        primary_key_names = list(getattr(table, "primary_keys", []) or [])
        if not primary_key_names and getattr(table, "primary_key", None):
            primary_key_names = [table.primary_key]

        if not primary_key_names:
            primary_key_names = [
                getattr(column, "name", "") or ""
                for column in getattr(table, "columns", []) or []
                if getattr(column, "primary_key", False)
            ]

        result: list[DB2Column] = []
        for primary_key_name in primary_key_names:
            column = self.find_column_by_name(
                table=table,
                column_name=primary_key_name,
            )
            if column is not None:
                result.append(column)

        return result

    def find_column_by_name(
        self,
        table: DB2Table,
        column_name: str,
    ) -> DB2Column | None:
        normalized_column_name = NameNormalizer.normalize(column_name or "")
        if not normalized_column_name:
            return None

        for column in getattr(table, "columns", []) or []:
            current_name = NameNormalizer.normalize(getattr(column, "name", "") or "")
            if current_name == normalized_column_name:
                return column

            if self.remove_record_suffix(current_name) == self.remove_record_suffix(
                normalized_column_name
            ):
                return column

        return None

    def find_column_for_field(
        self,
        record,
        field,
        column_lookup: dict[str, DB2Column],
        date_group_info: dict[str, dict],
    ) -> DB2Column | None:
        field_name = NameNormalizer.normalize(getattr(field, "name", "") or "")
        if not field_name:
            return None

        possible_names = [
            field_name,
            self.remove_record_suffix(field_name),
            self.convert_cobol_zone_to_db2_field_name(record=record, field=field),
            self.convert_date_field_to_db2_field_name(record=record, field=field),
        ]

        for name in possible_names:
            column = self.find_matching_column(
                field_name=name,
                column_lookup=column_lookup,
            )
            if column is not None:
                return column

        parsed_date_part = self.parse_date_part(field_name=field_name)
        if parsed_date_part is not None:
            date_key = parsed_date_part.get("date_key", "")
            column = self.find_matching_column(
                field_name=date_key,
                column_lookup=column_lookup,
            )
            if column is not None:
                return column

        return None

    def find_matching_column(
        self,
        field_name: str,
        column_lookup: dict[str, DB2Column],
    ) -> DB2Column | None:
        normalized = NameNormalizer.normalize(field_name or "")
        if normalized in column_lookup:
            return column_lookup[normalized]

        suffix_removed = self.remove_record_suffix(normalized)
        if suffix_removed and suffix_removed in column_lookup:
            return column_lookup[suffix_removed]

        return None

    def collect_date_group_info(
        self,
        fields,
    ) -> dict[str, dict]:
        date_group_info: dict[str, dict] = {}

        for field in fields or []:
            field_name = NameNormalizer.normalize(getattr(field, "name", "") or "")
            if not field_name:
                continue

            parsed = self.parse_date_part(field_name=field_name)
            if parsed is not None:
                date_key = parsed["date_key"]
                part = parsed["part"]
                if date_key not in date_group_info:
                    date_group_info[date_key] = {
                        "parts": {},
                        "actual_outer_field": None,
                    }
                date_group_info[date_key]["parts"][part] = field
                continue

            if self.looks_like_outer_date_field(field=field):
                date_key = field_name
                if date_key not in date_group_info:
                    date_group_info[date_key] = {
                        "parts": {},
                        "actual_outer_field": field,
                    }
                else:
                    date_group_info[date_key]["actual_outer_field"] = field

        return date_group_info

    def looks_like_outer_date_field(
        self,
        field,
    ) -> bool:
        field_name = NameNormalizer.normalize(getattr(field, "name", "") or "")
        if not field_name:
            return False

        tokens = self.split_name_tokens(field_name)
        if "DATE" not in tokens and not field_name.replace(" ", "_").endswith("_DATE"):
            return False

        length = self.get_field_length(field=field)
        try:
            if int(length) == 8:
                return True
        except Exception:
            pass

        datatype = str(getattr(field, "datatype", "") or "").upper()
        basetype = str(getattr(field, "basetype", "") or "").upper()

        return datatype == "DATE" or basetype == "DATE"

    def is_actual_outer_date_field(
        self,
        field,
        date_group_info: dict[str, dict],
    ) -> bool:
        field_name = NameNormalizer.normalize(getattr(field, "name", "") or "")
        if not field_name:
            return False

        for _date_key, group_info in date_group_info.items():
            actual_outer_field = group_info.get("actual_outer_field")
            if actual_outer_field is None:
                continue

            actual_outer_name = NameNormalizer.normalize(
                getattr(actual_outer_field, "name", "") or ""
            )

            if actual_outer_name == field_name:
                return True

            if self.remove_record_suffix(actual_outer_name) == self.remove_record_suffix(
                field_name
            ):
                return True

        return False

    def inferred_date_key_for_date_part(
        self,
        field_name: str,
    ) -> str | None:
        candidates = self.parse_date_part_candidates(field_name=field_name)
        if not candidates:
            return None
        return candidates[0]["date_key"]

    def parse_date_part(
        self,
        field_name: str,
    ) -> dict | None:
        candidates = self.parse_date_part_candidates(field_name=field_name)
        if not candidates:
            return None
        return candidates[0]

    def parse_date_part_candidates(
        self,
        field_name: str,
    ) -> list[dict]:
        tokens = self.split_name_tokens(field_name)
        if len(tokens) < 2:
            return []

        candidates = []
        for index, token in enumerate(tokens):
            part = self.date_part_type(token=token, tokens=tokens)
            if part is None:
                continue

            date_tokens = tokens.copy()
            date_tokens[index] = "DATE"

            candidates.append(
                {
                    "date_key": "_".join(date_tokens),
                    "part": part,
                    "tokens": date_tokens,
                }
            )

        return candidates

    def split_name_tokens(
        self,
        value: str,
    ) -> list[str]:
        normalized = str(value or "").upper().strip()
        normalized = NameNormalizer.normalize(normalized)
        if not normalized:
            return []
        return [
            token
            for token in re.split(r"[\s_]+", normalized)
            if token
        ]

    def date_part_type(
        self,
        token: str,
        tokens: list[str],
    ) -> str | None:
        token = token.upper()
        has_dy_dm_dd = "DY" in tokens and "DM" in tokens and "DD" in tokens

        if token in {"YEAR", "YR", "Y", "YY", "YYYY"}:
            return "YEAR"
        if token in {"MONTH", "MON", "MO", "M", "MM", "DM"}:
            return "MONTH"
        if token in {"DAY", "D", "DD"}:
            return "DAY"
        if token == "DY":
            if has_dy_dm_dd:
                return "YEAR"
            return "DAY"

        return None

    def db2_key_label(
        self,
        table: DB2Table | None,
        column: DB2Column | None,
    ) -> str:
        if table is None or column is None:
            return ""

        labels = []
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
            foreign_key_column_name = NameNormalizer.normalize(
                self.get_foreign_key_column_name(foreign_key=foreign_key)
            )
            if column_name == foreign_key_column_name:
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
            or ""
        )

    def get_relationship_set_name(
        self,
        relationship,
    ) -> str:
        return (
            getattr(relationship, "set_name", None)
            or getattr(relationship, "name", None)
            or getattr(relationship, "set", None)
            or ""
        )

    def get_relationship_owner_record(
        self,
        relationship,
    ) -> str:
        return (
            getattr(relationship, "owner_record", None)
            or getattr(relationship, "parent_record", None)
            or getattr(relationship, "owner", None)
            or getattr(relationship, "parent", None)
            or ""
        )

    def get_relationship_member_record(
        self,
        relationship,
    ) -> str:
        return (
            getattr(relationship, "member_record", None)
            or getattr(relationship, "child_record", None)
            or getattr(relationship, "member", None)
            or getattr(relationship, "child", None)
            or ""
        )

    def build_table_lookup(
        self,
        db2_model: DB2Model,
    ) -> dict[str, DB2Table]:
        lookup: dict[str, DB2Table] = {}
        if db2_model is None:
            return lookup
        for table in getattr(db2_model, "tables", []) or []:
            table_name = getattr(table, "name", "") or ""
            normalized_table_name = NameNormalizer.normalize(table_name)
            if normalized_table_name:
                lookup[normalized_table_name] = table
            suffix_removed = self.remove_record_suffix(normalized_table_name)
            if suffix_removed:
                lookup[suffix_removed] = table
        return lookup

    def build_column_lookup(
        self,
        table: DB2Table,
    ) -> dict[str, DB2Column]:
        lookup: dict[str, DB2Column] = {}
        for column in getattr(table, "columns", []) or []:
            column_name = getattr(column, "name", "") or ""
            normalized_column_name = NameNormalizer.normalize(column_name)
            if normalized_column_name:
                lookup[normalized_column_name] = column
            suffix_removed = self.remove_record_suffix(normalized_column_name)
            if suffix_removed:
                lookup[suffix_removed] = column
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

    def find_table_for_record(
        self,
        record_name: str,
        table_lookup: dict[str, DB2Table],
    ) -> DB2Table | None:
        normalized_record_name = NameNormalizer.normalize(record_name)
        if normalized_record_name in table_lookup:
            return table_lookup[normalized_record_name]
        suffix_removed = self.remove_record_suffix(normalized_record_name)
        if suffix_removed and suffix_removed in table_lookup:
            return table_lookup[suffix_removed]
        return None

    def is_date_field(
        self,
        field,
    ) -> bool:
        datatype = str(getattr(field, "datatype", "") or "").upper()
        basetype = str(getattr(field, "basetype", "") or "").upper()
        field_name = NameNormalizer.normalize(getattr(field, "name", "") or "")
        normalized_name = field_name.replace(" ", "_")
        return (
            datatype == "DATE"
            or basetype == "DATE"
            or normalized_name.endswith("_DATE")
            or normalized_name == "DATE"
            or "_DATE_" in normalized_name
        )

    def is_filler_field(
        self,
        field,
    ) -> bool:
        field_name = getattr(field, "name", "") or ""
        return field_name.upper().startswith("FILLER")

    def format_cobol_zone(
        self,
        field,
    ) -> str:
        level = getattr(field, "level", None)
        name = getattr(field, "name", "") or ""
        if level is None:
            return name
        return self.format_cobol_level_and_name(level=level, name=name)

    def format_cobol_level_and_name(
        self,
        level,
        name,
    ) -> str:
        if level is None:
            return str(name or "")
        try:
            level_text = f"{int(level):02d}"
        except Exception:
            level_text = str(level)
        return f"{level_text} {name}"

    def get_field_picture(
        self,
        field,
    ) -> str:
        picture = (
            getattr(field, "picture", None)
            or getattr(field, "pic", None)
            or getattr(field, "pic_clause", None)
            or ""
        )
        if not picture:
            return ""
        text = str(picture).strip()
        if text.upper().startswith("PIC"):
            return text
        return f"PIC {text}"

    def get_field_length(
        self,
        field,
    ):
        return (
            getattr(field, "length", None)
            or getattr(field, "storage_length", None)
            or getattr(field, "physical_length", None)
            or ""
        )

    def get_field_end_position(
        self,
        field,
    ):
        end_position = (
            getattr(field, "end_position", None)
            or getattr(field, "field_end_position", None)
            or None
        )
        if end_position is not None:
            return end_position
        start = (
            getattr(field, "start_position", None)
            or getattr(field, "start", None)
            or None
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
            or ""
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
            or ""
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
        return {column: "" for column in self.COLUMNS}

    def to_string(
        self,
        value,
    ) -> str:
        if value is None:
            return ""
        return str(value)

    def to_db2_name(
        self,
        value,
    ) -> str:
        text = str(value or "").strip().upper()
        text = text.replace("-", "_")
        text = text.replace(" ", "_")
        text = re.sub(r"[^A-Z0-9_]", "_", text)
        text = re.sub(r"_+", "_", text)
        return text.strip("_")

    def remove_record_suffix(
        self,
        value: str,
    ) -> str:
        text = NameNormalizer.normalize(value or "")
        if not text:
            return ""
        text = text.replace(" ", "_")
        return re.sub(r"_[0-9]{4}$", "", text)