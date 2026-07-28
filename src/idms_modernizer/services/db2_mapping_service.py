import re

from collections import defaultdict

from idms_modernizer.domain.canonical_models import CanonicalSchema
from idms_modernizer.domain.db2_models import (
    DB2Column,
    DB2ForeignKey,
    DB2Model,
    DB2Table,
)
from idms_modernizer.services.db2_datatype_mapper import DB2DatatypeMapper


class DB2MappingService:
    """
    Builds DB2 model from canonical schema.

    Generic behavior only:
    - No hardcoded table names.
    - No hardcoded column names.
    - No hardcoded SET names.
    - Converts detected IDMS owner/member SETs into DB2 foreign keys.
    - Uses every owner PK column for FK columns.
    - If owner has composite PK, every PK column becomes one FK column.
    - If a record has no PK, creates ID_RECORD_<record_name> CHAR(20).
    """

    TECHNICAL_KEY_DATATYPE = "CHAR(20)"

    def build_db2_model(
        self,
        schema: CanonicalSchema,
    ) -> DB2Model:
        tables: list[DB2Table] = []

        for record in getattr(schema, "records", []) or []:
            record_name = getattr(record, "name", "") or ""

            table = DB2Table(
                name=self.normalize_table_name(record_name),
                columns=[],
                foreign_keys=[],
                primary_key=None,
                primary_keys=[],
            )

            declared_primary_keys = self.get_record_primary_keys(
                record=record,
            )

            table.primary_keys = [
                self.normalize_column_name(primary_key)
                for primary_key in declared_primary_keys
                if primary_key
            ]

            if table.primary_keys:
                table.primary_key = table.primary_keys[0]

            added_columns: set[str] = set()

            for field in getattr(record, "fields", []) or []:
                column_name = self.normalize_column_name(
                    getattr(field, "name", "") or "",
                )

                if not column_name:
                    continue

                if column_name in added_columns:
                    continue

                is_primary_key = column_name in table.primary_keys

                table.columns.append(
                    DB2Column(
                        name=column_name,
                        datatype=DB2DatatypeMapper.map(field),
                        nullable=not is_primary_key,
                        primary_key=is_primary_key,
                        generated=False,
                        source_kind="COBOL",
                    )
                )

                added_columns.add(column_name)

            self.ensure_record_primary_key(
                table=table,
                record_name=record_name,
            )

            tables.append(table)

        set_relationships = self.collect_set_relationships(
            schema=schema,
        )

        relationship_pairs = self.detect_relationship_pairs(
            set_relationships=set_relationships,
            tables=tables,
        )

        self.add_foreign_keys_from_sets(
            set_relationships=set_relationships,
            tables=tables,
            relationship_pairs=relationship_pairs,
        )

        return DB2Model(
            tables=tables,
        )

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
                primary_keys.append(str(explicit_primary_keys))

        primary_key = getattr(record, "primary_key", None)

        if primary_key:
            primary_keys.append(primary_key)

        cleaned: list[str] = []

        for primary_key_value in primary_keys:
            normalized = self.normalize_column_name(primary_key_value)

            if not normalized:
                continue

            if normalized in cleaned:
                continue

            cleaned.append(normalized)

        return cleaned

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
            primary_key_columns.append(column)

        if primary_key_columns:
            table.primary_keys = [
                column.name
                for column in primary_key_columns
            ]
            table.primary_key = table.primary_keys[0]
            return primary_key_columns

        generated_pk_name = self.generated_record_pk_name(
            record_name=record_name or table.name,
        )

        existing_column = self.find_column(
            table=table,
            column_name=generated_pk_name,
        )

        if existing_column is not None:
            existing_column.nullable = False
            existing_column.primary_key = True
            existing_column.generated = True
            existing_column.source_kind = "GENERATED_PK"

            table.primary_keys = [existing_column.name]
            table.primary_key = existing_column.name

            return [existing_column]

        generated_column = DB2Column(
            name=generated_pk_name,
            datatype=self.TECHNICAL_KEY_DATATYPE,
            nullable=False,
            primary_key=True,
            generated=True,
            source_kind="GENERATED_PK",
        )

        table.columns.insert(
            0,
            generated_column,
        )

        table.primary_keys = [generated_column.name]
        table.primary_key = generated_column.name

        return [generated_column]

    def generated_record_pk_name(
        self,
        record_name: str,
    ) -> str:
        normalized_record_name = self.normalize_column_name(
            record_name,
        )

        return f"ID_RECORD_{normalized_record_name}"

    def collect_set_relationships(
        self,
        schema: CanonicalSchema,
    ) -> list[dict[str, str]]:
        relationships: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()

        for set_def in getattr(schema, "sets", []) or []:
            set_name = self.normalize_column_name(
                self.get_attr(set_def, "name")
                or self.get_attr(set_def, "set_name")
                or ""
            )

            owner_record = self.normalize_table_name(
                self.get_attr(set_def, "owner_record")
                or self.get_attr(set_def, "parent_record")
                or self.get_attr(set_def, "owner")
                or self.get_attr(set_def, "parent")
                or ""
            )

            member_record = self.normalize_table_name(
                self.get_attr(set_def, "member_record")
                or self.get_attr(set_def, "child_record")
                or self.get_attr(set_def, "member")
                or self.get_attr(set_def, "child")
                or ""
            )

            self.add_set_relationship_if_valid(
                relationships=relationships,
                seen=seen,
                set_name=set_name,
                owner_record=owner_record,
                member_record=member_record,
            )

        for relationship in getattr(schema, "relationships", []) or []:
            set_name = self.normalize_column_name(
                self.get_attr(relationship, "set_name")
                or self.get_attr(relationship, "name")
                or self.get_attr(relationship, "set")
                or ""
            )

            owner_record = self.normalize_table_name(
                self.get_attr(relationship, "owner_record")
                or self.get_attr(relationship, "parent_record")
                or self.get_attr(relationship, "owner")
                or self.get_attr(relationship, "parent")
                or ""
            )

            member_record = self.normalize_table_name(
                self.get_attr(relationship, "member_record")
                or self.get_attr(relationship, "child_record")
                or self.get_attr(relationship, "member")
                or self.get_attr(relationship, "child")
                or ""
            )

            self.add_set_relationship_if_valid(
                relationships=relationships,
                seen=seen,
                set_name=set_name,
                owner_record=owner_record,
                member_record=member_record,
            )

        return relationships

    def add_set_relationship_if_valid(
        self,
        relationships: list[dict[str, str]],
        seen: set[tuple[str, str, str]],
        set_name: str,
        owner_record: str,
        member_record: str,
    ) -> None:
        if not set_name:
            return

        if not owner_record:
            return

        if not member_record:
            return

        if set_name == "CALC":
            return

        key = (
            set_name,
            owner_record,
            member_record,
        )

        if key in seen:
            return

        seen.add(key)

        relationships.append(
            {
                "set_name": set_name,
                "owner_record": owner_record,
                "member_record": member_record,
            }
        )

    def detect_relationship_pairs(
        self,
        set_relationships: list[dict[str, str]],
        tables: list[DB2Table],
    ) -> dict[tuple[str, str], set[str]]:
        relationship_pairs: dict[tuple[str, str], set[str]] = defaultdict(set)

        for relationship in set_relationships:
            set_name = relationship.get("set_name", "")
            owner_record = relationship.get("owner_record", "")
            member_record = relationship.get("member_record", "")

            owner_table = self.find_table(
                tables=tables,
                table_name=owner_record,
            )

            member_table = self.find_table(
                tables=tables,
                table_name=member_record,
            )

            if owner_table is None:
                continue

            if member_table is None:
                continue

            if not set_name:
                continue

            relationship_pairs[
                (
                    owner_table.name,
                    member_table.name,
                )
            ].add(set_name)

        return relationship_pairs

    def add_foreign_keys_from_sets(
        self,
        set_relationships: list[dict[str, str]],
        tables: list[DB2Table],
        relationship_pairs: dict[tuple[str, str], set[str]],
    ) -> None:
        for relationship in set_relationships:
            set_name = relationship.get("set_name", "")
            owner_record = relationship.get("owner_record", "")
            member_record = relationship.get("member_record", "")

            if not set_name:
                continue

            if not owner_record:
                continue

            if not member_record:
                continue

            owner_table = self.find_table(
                tables=tables,
                table_name=owner_record,
            )

            member_table = self.find_table(
                tables=tables,
                table_name=member_record,
            )

            if owner_table is None:
                continue

            if member_table is None:
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
                fk_column = self.ensure_set_specific_fk_column(
                    child_table=member_table,
                    set_name=set_name,
                    parent_pk_column=owner_pk_column,
                )

                self.add_foreign_key_if_missing(
                    child_table=member_table,
                    child_column=fk_column.name,
                    parent_table=owner_table,
                    parent_column=owner_pk_column.name,
                    set_name=set_name,
                )

    def get_primary_key_columns(
        self,
        table: DB2Table,
    ) -> list[DB2Column]:
        primary_key_names = list(getattr(table, "primary_keys", []) or [])

        if not primary_key_names and getattr(table, "primary_key", None):
            primary_key_names = [table.primary_key]

        if not primary_key_names:
            primary_key_names = [
                getattr(column, "name", "")
                for column in getattr(table, "columns", []) or []
                if getattr(column, "primary_key", False)
            ]

        columns: list[DB2Column] = []

        for primary_key_name in primary_key_names:
            column = self.find_column(
                table=table,
                column_name=primary_key_name,
            )

            if column is None:
                continue

            column.primary_key = True
            column.nullable = False

            columns.append(column)

        return columns

    def ensure_set_specific_fk_column(
        self,
        child_table: DB2Table,
        set_name: str,
        parent_pk_column: DB2Column,
    ) -> DB2Column:
        column_name = self.normalize_column_name(
            f"{set_name}_{parent_pk_column.name}",
        )

        existing_column = self.find_column(
            table=child_table,
            column_name=column_name,
        )

        if existing_column is not None:
            existing_column.nullable = True
            existing_column.generated = True
            existing_column.source_kind = "SET_FK"
            return existing_column

        new_column = DB2Column(
            name=column_name,
            datatype=parent_pk_column.datatype,
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
                set_name=self.normalize_column_name(set_name),
            )
        )

    def foreign_key_exists(
        self,
        child_table: DB2Table,
        child_column: str,
        parent_table: DB2Table,
        parent_column: str,
    ) -> bool:
        normalized_child_column = self.normalize_column_name(child_column)
        normalized_parent_table = self.normalize_table_name(parent_table.name)
        normalized_parent_column = self.normalize_column_name(parent_column)

        for existing_fk in getattr(child_table, "foreign_keys", []) or []:
            if (
                self.normalize_column_name(existing_fk.column_name)
                == normalized_child_column
                and self.normalize_table_name(existing_fk.reference_table)
                == normalized_parent_table
                and self.normalize_column_name(existing_fk.reference_column)
                == normalized_parent_column
            ):
                return True

        return False

    def find_table(
        self,
        tables: list[DB2Table],
        table_name: str | None,
    ) -> DB2Table | None:
        normalized_name = self.normalize_table_name(table_name)

        if not normalized_name:
            return None

        for table in tables:
            table_normalized = self.normalize_table_name(table.name)

            if table_normalized == normalized_name:
                return table

            if self.remove_record_suffix(table_normalized) == self.remove_record_suffix(normalized_name):
                return table

        return None

    def find_column(
        self,
        table: DB2Table,
        column_name: str | None,
    ) -> DB2Column | None:
        normalized_name = self.normalize_column_name(column_name)

        if not normalized_name:
            return None

        for column in getattr(table, "columns", []) or []:
            column_normalized = self.normalize_column_name(column.name)

            if column_normalized == normalized_name:
                return column

            if self.remove_record_suffix(column_normalized) == self.remove_record_suffix(normalized_name):
                return column

        return None

    def get_attr(
        self,
        source,
        name: str,
    ):
        if source is None:
            return None

        if isinstance(source, dict):
            return source.get(name)

        return getattr(source, name, None)

    def normalize_table_name(
        self,
        value,
    ) -> str:
        return self.normalize_name(value=value)

    def normalize_column_name(
        self,
        value,
    ) -> str:
        return self.normalize_name(value=value)

    def normalize_name(
        self,
        value,
    ) -> str:
        text = str(value or "").strip().upper()

        if not text:
            return ""

        text = text.replace("-", "_")
        text = text.replace(" ", "_")
        text = re.sub(r"[^A-Z0-9_]", "_", text)
        text = re.sub(r"_+", "_", text)
        text = text.strip("_")

        return text

    def remove_record_suffix(
        self,
        value: str,
    ) -> str:
        text = self.normalize_name(value)

        if not text:
            return ""

        return re.sub(
            r"_[0-9]{4}$",
            "",
            text,
        )