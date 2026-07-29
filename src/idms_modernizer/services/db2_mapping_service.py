import re

from idms_modernizer.domain.canonical_models import CanonicalSchema
from idms_modernizer.domain.db2_models import (
    DB2Column,
    DB2ForeignKey,
    DB2Model,
    DB2Table,
)
from idms_modernizer.services.db2_datatype_mapper import DB2DatatypeMapper


print("LOADED DB2MappingService VERSION NAMING-FK-DATE-FIX-2026-07-29")


class DB2MappingService:
    """
    Builds DB2 model from canonical schema.

    Naming rules implemented:

    1. Normal COBOL business field:
       - Start from COBOL business field.
       - Normalize separators to underscore.
       - Apply project abbreviations.
       - Remove generic trailing qualifiers where applicable.
       - Append _479<record-code>.

       Example:
       NR-CIO-FORM-AS in VMBSIC -> NR_CIOFMAS_479BSIC
       CT-RK-TGDSV in VMBFORM   -> CT_RKTGDSV_479FORM
       NR-ID-STOCK in VMBCOUP   -> NR_IDSTOCK_479COUP

    2. Date field:
       - Outer COBOL date field becomes one DB2 DATE column.
       - DB2 date name keeps DA prefix.
       - Append _479<record-code>.

       Example:
       DA-CPTA-GDIFC -> DA_CPTA_479MBFC
       DA-UB-GDIFR   -> DA_UBDATE_479MBFR

    3. Foreign key:
       - FK column reuses exact referenced/master DB2 column name.
       - No SET prefix is added to FK column names.
       - Relationship/set name is metadata only.

       Example:
       Master PK: NR_CIOFMAS_479BSIC
       Child FK : NR_CIOFMAS_479BSIC

    4. Missing PK:
       - If no primary key exists, create generated technical key:
         ID_RECORD_<record-code>
       - Type: CHAR(20)
    """

    TECHNICAL_KEY_DATATYPE = "CHAR(20)"

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

    PROJECT_ABBREVIATIONS = {
        "FORM": "FM",
        "EVPRCP": "ERCP",
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

    def build_db2_model(
        self,
        schema: CanonicalSchema,
    ) -> DB2Model:
        print("USING DB2MappingService.build_db2_model VERSION NAMING-FK-DATE-FIX-2026-07-29")

        tables: list[DB2Table] = []

        for record in getattr(schema, "records", []) or []:
            record_name = getattr(record, "name", "") or ""
            table_name = self.normalize_table_name(record_name)

            table = DB2Table(
                name=table_name,
                columns=[],
                foreign_keys=[],
                primary_key=None,
                primary_keys=[],
            )

            declared_primary_keys = self.get_record_primary_keys(
                record=record,
            )

            normalized_primary_keys = []

            for primary_key in declared_primary_keys:
                normalized_primary_key = self.normalize_column_name(
                    value=primary_key,
                    record_name=record_name,
                    field=None,
                )

                if normalized_primary_key and normalized_primary_key not in normalized_primary_keys:
                    normalized_primary_keys.append(normalized_primary_key)

            table.primary_keys = normalized_primary_keys

            if table.primary_keys:
                table.primary_key = table.primary_keys[0]

            added_columns: set[str] = set()

            for field in getattr(record, "fields", []) or []:
                raw_field_name = getattr(field, "name", "") or ""

                column_name = self.normalize_column_name(
                    value=raw_field_name,
                    record_name=record_name,
                    field=field,
                )

                if not column_name:
                    continue

                if column_name in added_columns:
                    continue

                is_primary_key = column_name in table.primary_keys

                column = DB2Column(
                    name=column_name,
                    datatype=DB2DatatypeMapper.map(field),
                    nullable=not is_primary_key,
                    primary_key=is_primary_key,
                    generated=False,
                    source_kind="COBOL",
                )

                table.columns.append(column)
                added_columns.add(column_name)

            self.ensure_record_primary_key(
                table=table,
                record_name=record_name,
            )

            tables.append(table)

        model = DB2Model(
            tables=tables,
        )

        self.apply_relationship_foreign_keys(
            schema=schema,
            model=model,
        )

        return model

    def apply_relationship_foreign_keys(
        self,
        schema: CanonicalSchema,
        model: DB2Model,
    ) -> None:
        table_lookup = self.build_table_lookup(
            model=model,
        )

        for relationship in getattr(schema, "relationships", []) or []:
            set_name = self.get_relationship_set_name(
                relationship=relationship,
            )

            owner_record = self.get_relationship_owner_record(
                relationship=relationship,
            )

            member_record = self.get_relationship_member_record(
                relationship=relationship,
            )

            if not owner_record or not member_record:
                continue

            owner_table = self.find_table_for_record(
                record_name=owner_record,
                table_lookup=table_lookup,
            )

            member_table = self.find_table_for_record(
                record_name=member_record,
                table_lookup=table_lookup,
            )

            if owner_table is None or member_table is None:
                continue

            owner_pk_columns = self.get_primary_key_columns(
                table=owner_table,
            )

            if not owner_pk_columns:
                owner_pk_columns = self.ensure_record_primary_key(
                    table=owner_table,
                    record_name=owner_record,
                )

            for owner_pk_column in owner_pk_columns:
                fk_column = self.ensure_fk_column_reusing_parent_name(
                    child_table=member_table,
                    parent_pk_column=owner_pk_column,
                )

                self.add_foreign_key_if_missing(
                    child_table=member_table,
                    child_column=fk_column.name,
                    parent_table=owner_table,
                    parent_column=owner_pk_column.name,
                    set_name=set_name,
                )

    def ensure_fk_column_reusing_parent_name(
        self,
        child_table: DB2Table,
        parent_pk_column: DB2Column,
    ) -> DB2Column:
        column_name = getattr(parent_pk_column, "name", "") or ""

        existing_column = self.find_column(
            table=child_table,
            column_name=column_name,
        )

        if existing_column is not None:
            existing_column.nullable = True
            existing_column.generated = True
            existing_column.primary_key = False
            existing_column.source_kind = "SET_FK"

            if not getattr(existing_column, "datatype", None):
                existing_column.datatype = getattr(parent_pk_column, "datatype", "") or ""

            return existing_column

        new_column = DB2Column(
            name=column_name,
            datatype=getattr(parent_pk_column, "datatype", "") or self.TECHNICAL_KEY_DATATYPE,
            nullable=True,
            primary_key=False,
            generated=True,
            source_kind="SET_FK",
        )

        child_table.columns.append(new_column)

        return new_column

    def add_foreign_key_if_missing(
        self,
        child_table: DB2Table,
        child_column: str,
        parent_table: DB2Table,
        parent_column: str,
        set_name: str = "",
    ) -> None:
        if self.foreign_key_exists(
            child_table=child_table,
            child_column=child_column,
            parent_table=parent_table,
            parent_column=parent_column,
        ):
            return

        child_table.foreign_keys.append(
            DB2ForeignKey(
                column_name=child_column,
                reference_table=parent_table.name,
                reference_column=parent_column,
                set_name=self.normalize_name(set_name),
            )
        )

    def foreign_key_exists(
        self,
        child_table: DB2Table,
        child_column: str,
        parent_table: DB2Table,
        parent_column: str,
    ) -> bool:
        normalized_child_column = self.normalize_name(child_column)
        normalized_parent_table = self.normalize_name(parent_table.name)
        normalized_parent_column = self.normalize_name(parent_column)

        for foreign_key in getattr(child_table, "foreign_keys", []) or []:
            existing_child_column = self.normalize_name(
                getattr(foreign_key, "column_name", "") or ""
            )
            existing_parent_table = self.normalize_name(
                getattr(foreign_key, "reference_table", "") or ""
            )
            existing_parent_column = self.normalize_name(
                getattr(foreign_key, "reference_column", "") or ""
            )

            if (
                existing_child_column == normalized_child_column
                and existing_parent_table == normalized_parent_table
                and existing_parent_column == normalized_parent_column
            ):
                return True

        return False

    def ensure_record_primary_key(
        self,
        table: DB2Table,
        record_name: str,
    ) -> list[DB2Column]:
        primary_key_columns: list[DB2Column] = []

        for primary_key_name in list(getattr(table, "primary_keys", []) or []):
            column = self.find_column(
                table=table,
                column_name=primary_key_name,
            )

            if column is None:
                continue

            column.nullable = False
            column.primary_key = True

            if not getattr(column, "source_kind", ""):
                column.source_kind = "COBOL"

            primary_key_columns.append(column)

        if primary_key_columns:
            table.primary_keys = [
                column.name
                for column in primary_key_columns
            ]
            table.primary_key = table.primary_keys[0]

            return primary_key_columns

        generated_pk_name = self.generated_primary_key_name(
            record_name=record_name,
        )

        existing_generated = self.find_column(
            table=table,
            column_name=generated_pk_name,
        )

        if existing_generated is not None:
            existing_generated.nullable = False
            existing_generated.primary_key = True
            existing_generated.generated = True
            existing_generated.source_kind = "GENERATED PK"

            table.primary_keys = [existing_generated.name]
            table.primary_key = existing_generated.name

            return [existing_generated]

        generated_column = DB2Column(
            name=generated_pk_name,
            datatype=self.TECHNICAL_KEY_DATATYPE,
            nullable=False,
            primary_key=True,
            generated=True,
            source_kind="GENERATED PK",
        )

        table.columns.insert(0, generated_column)
        table.primary_keys = [generated_column.name]
        table.primary_key = generated_column.name

        return [generated_column]

    def generated_primary_key_name(
        self,
        record_name: str,
    ) -> str:
        record_code = self.record_code(record_name)

        if record_code:
            return f"ID_RECORD_{record_code}"

        table_name = self.normalize_table_name(record_name)

        if table_name:
            return f"ID_RECORD_{table_name}"

        return "ID_RECORD"

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
            column = self.find_column(
                table=table,
                column_name=primary_key_name,
            )

            if column is not None:
                result.append(column)

        return result

    def find_column(
        self,
        table: DB2Table,
        column_name: str,
    ) -> DB2Column | None:
        normalized_column_name = self.normalize_name(column_name)

        if not normalized_column_name:
            return None

        for column in getattr(table, "columns", []) or []:
            current_name = self.normalize_name(
                getattr(column, "name", "") or ""
            )

            if current_name == normalized_column_name:
                return column

        return None

    def build_table_lookup(
        self,
        model: DB2Model,
    ) -> dict[str, DB2Table]:
        lookup: dict[str, DB2Table] = {}

        for table in getattr(model, "tables", []) or []:
            table_name = getattr(table, "name", "") or ""
            normalized_table_name = self.normalize_name(table_name)

            if normalized_table_name:
                lookup[normalized_table_name] = table

            suffix_removed = self.remove_record_suffix(
                normalized_table_name,
            )

            if suffix_removed:
                lookup[suffix_removed] = table

        return lookup

    def find_table_for_record(
        self,
        record_name: str,
        table_lookup: dict[str, DB2Table],
    ) -> DB2Table | None:
        normalized_record_name = self.normalize_table_name(record_name)

        if normalized_record_name in table_lookup:
            return table_lookup[normalized_record_name]

        suffix_removed = self.remove_record_suffix(
            normalized_record_name,
        )

        if suffix_removed in table_lookup:
            return table_lookup[suffix_removed]

        for table_key, table in table_lookup.items():
            if self.remove_record_suffix(table_key) == suffix_removed:
                return table

        return None

    def normalize_table_name(
        self,
        value: str | None,
    ) -> str:
        return self.to_db2_name(value or "")

    def normalize_column_name(
        self,
        value: str | None,
        record_name: str | None,
        field=None,
    ) -> str:
        raw_value = str(value or "").strip()

        if not raw_value:
            return ""

        if field is not None and self.is_date_field(field=field):
            return self.date_column_name(
                field_name=raw_value,
                record_name=record_name,
            )

        return self.normal_business_column_name(
            field_name=raw_value,
            record_name=record_name,
        )

    def normal_business_column_name(
        self,
        field_name: str,
        record_name: str | None,
    ) -> str:
        base = self.business_field_base_name(
            field_name=field_name,
        )

        record_code = self.record_code(record_name)

        if record_code:
            return f"{base}_479{record_code}"

        return base

    def date_column_name(
        self,
        field_name: str,
        record_name: str | None,
    ) -> str:
        base = self.date_field_base_name(
            field_name=field_name,
        )

        record_code = self.record_code(record_name)

        if record_code:
            return f"{base}_479{record_code}"

        return base

    def business_field_base_name(
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

        parts = self.remove_generic_trailing_tokens(
            parts=parts,
        )

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
        record_name: str | None,
    ) -> str:
        normalized = self.to_db2_name(record_name or "")
        compact = re.sub(r"[^A-Z0-9]", "", normalized)

        if not compact:
            return ""

        if len(compact) <= 4:
            return compact

        return compact[-4:]

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

        basetype = str(
            getattr(field, "basetype", None)
            or getattr(field, "base_type", None)
            or "",
        ).strip().upper()

        if datatype == "DATE" or basetype == "DATE":
            return True

        field_name = getattr(field, "name", "") or ""

        if self.is_date_like_name(field_name):
            picture = str(
                getattr(field, "picture", None)
                or getattr(field, "pic", None)
                or getattr(field, "pic_clause", None)
                or "",
            ).strip()

            if self.is_yyyymmdd_picture(picture):
                return True

        return False

    def is_yyyymmdd_picture(
        self,
        picture: str,
    ) -> bool:
        if not picture:
            return False

        clean = DB2DatatypeMapper.clean_picture(
            picture=picture,
        )
        core = DB2DatatypeMapper.picture_core(
            picture=clean,
        )

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
        parts = self.name_parts(value)

        if not parts:
            return False

        if parts[0] == "DA":
            return True

        if any(part in self.DATE_TOKENS for part in parts):
            return True

        compact = "".join(parts)

        return any(token in compact for token in self.DATE_TOKENS)

    def is_date_part_name(
        self,
        value: str,
    ) -> bool:
        parts = self.name_parts(value)

        for part in parts:
            if part in self.YEAR_PARTS:
                return True

            if part in self.MONTH_PARTS:
                return True

            if part in self.DAY_PARTS:
                return True

        return False

    def get_record_primary_keys(
        self,
        record,
    ) -> list[str]:
        primary_keys: list[str] = []

        explicit_primary_keys = getattr(record, "primary_keys", None)

        if explicit_primary_keys:
            if isinstance(explicit_primary_keys, list):
                primary_keys.extend(explicit_primary_keys)
            else:
                primary_keys.append(explicit_primary_keys)

        primary_key = getattr(record, "primary_key", None)

        if primary_key:
            primary_keys.append(primary_key)

        cleaned: list[str] = []

        for primary_key_value in primary_keys:
            normalized = self.normalize_name(
                primary_key_value,
            )

            if not normalized:
                continue

            if normalized in cleaned:
                continue

            cleaned.append(normalized)

        return cleaned

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

    def normalize_name(
        self,
        value: str | None,
    ) -> str:
        return self.to_db2_name(value or "")

    def to_db2_name(
        self,
        value: str | None,
    ) -> str:
        text = str(value or "").strip().upper()

        text = text.replace("\u00a0", " ")
        text = text.replace("\t", " ")

        text = re.sub(r"[^A-Z0-9]+", "_", text)
        text = re.sub(r"_+", "_", text)
        text = text.strip("_")

        return text

    def name_parts(
        self,
        value: str | None,
    ) -> list[str]:
        normalized = self.to_db2_name(value or "")

        return [
            part
            for part in normalized.split("_")
            if part
        ]

    def remove_record_suffix(
        self,
        name: str | None,
    ) -> str:
        value = str(name or "").strip().upper()

        value = re.sub(r"[_\-\s]+[0-9]{4}$", "", value)
        value = re.sub(r"[0-9]{4}$", "", value)
        value = re.sub(r"[_\-\s]+$", "", value)

        return value