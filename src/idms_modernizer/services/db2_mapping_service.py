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
from idms_modernizer.services.db2_name_normalizer import DB2NameNormalizer


class DB2MappingService:
    """
    Builds DB2 model from canonical schema.

    Generic behavior only:
    - No hardcoded table names.
    - No hardcoded suffix map.
    - No ignored token list.
    - Converts detected IDMS owner/member sets into DB2 foreign keys.
    - If multiple sets exist between the same owner/member pair, creates
      separate set-specific FK columns.
    - Uses natural owner PK when available.
    - Creates generic technical owner PK only when an owner has no PK.
    - Infers business-code FKs only by exact base-name match after removing
      trailing four-digit IDMS suffix.
    """

    TECHNICAL_KEY_DATATYPE = "BIGINT"

    def build_db2_model(
        self,
        schema: CanonicalSchema,
    ) -> DB2Model:
        tables: list[DB2Table] = []

        for record in schema.records:
            table = DB2Table(
                name=self.normalize_table_name(record.name),
                columns=[],
                foreign_keys=[],
                primary_key=(
                    self.normalize_column_name(record.primary_key)
                    if record.primary_key
                    else None
                ),
            )

            added_columns: set[str] = set()

            for field in record.fields:
                column_name = self.normalize_column_name(field.name)

                if not column_name:
                    continue

                if column_name in added_columns:
                    continue

                is_primary_key = (
                    table.primary_key is not None
                    and column_name == table.primary_key
                )

                table.columns.append(
                    DB2Column(
                        name=column_name,
                        datatype=DB2DatatypeMapper.map(field),
                        nullable=not is_primary_key,
                        primary_key=is_primary_key,
                    )
                )

                added_columns.add(column_name)

            self.ensure_declared_primary_key_column(table)
            tables.append(table)

        relationship_pairs = self.detect_relationship_pairs(
            schema=schema,
            tables=tables,
        )

        self.add_foreign_keys_from_sets(
            schema=schema,
            tables=tables,
            relationship_pairs=relationship_pairs,
        )

        self.add_foreign_keys_from_matching_primary_keys(
            tables=tables,
            relationship_pairs=relationship_pairs,
        )

        return DB2Model(
            tables=tables,
        )

    def ensure_declared_primary_key_column(
        self,
        table: DB2Table,
    ) -> None:
        if not table.primary_key:
            return

        primary_key_column = self.find_column(
            table=table,
            column_name=table.primary_key,
        )

        if primary_key_column is None:
            return

        primary_key_column.nullable = False
        primary_key_column.primary_key = True

    def detect_relationship_pairs(
        self,
        schema: CanonicalSchema,
        tables: list[DB2Table],
    ) -> dict[tuple[str, str], set[str]]:
        """
        Builds owner/member pair map from detected canonical sets.

        Result:
            {
                ("EMPLOYEE", "STRUCTURE"): {"MANAGES", "REPORTS_TO"}
            }
        """

        relationship_pairs: dict[tuple[str, str], set[str]] = defaultdict(set)

        for set_def in schema.sets:
            set_name = self.normalize_column_name(
                self.get_attr(
                    set_def,
                    "name",
                )
                or self.get_attr(
                    set_def,
                    "set_name",
                )
            )

            owner_record = self.get_attr(
                set_def,
                "owner_record",
            )

            member_record = self.get_attr(
                set_def,
                "member_record",
            )

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
        schema: CanonicalSchema,
        tables: list[DB2Table],
        relationship_pairs: dict[tuple[str, str], set[str]],
    ) -> None:
        """
        Converts detected IDMS owner/member sets into DB2 FKs.

        If multiple sets exist between same owner/member pair, each set gets
        its own FK column.

        Example:
            MANAGES + EMP_ID_0415 -> MANAGES_EMP_ID_0415
            REPORTS_TO + EMP_ID_0415 -> REPORTS_TO_EMP_ID_0415
        """

        for set_def in schema.sets:
            set_name = self.normalize_column_name(
                self.get_attr(
                    set_def,
                    "name",
                )
                or self.get_attr(
                    set_def,
                    "set_name",
                )
            )

            owner_record = self.get_attr(
                set_def,
                "owner_record",
            )

            member_record = self.get_attr(
                set_def,
                "member_record",
            )

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

            owner_pk_column = self.ensure_owner_primary_key(
                table=owner_table,
            )

            if owner_pk_column is None:
                continue

            pair_key = (
                owner_table.name,
                member_table.name,
            )

            has_multiple_sets_for_pair = (
                len(
                    relationship_pairs.get(
                        pair_key,
                        set(),
                    )
                )
                > 1
            )

            if has_multiple_sets_for_pair:
                fk_column = self.ensure_set_specific_fk_column(
                    child_table=member_table,
                    set_name=set_name,
                    parent_pk_column=owner_pk_column,
                )
            else:
                fk_column = self.find_existing_fk_column_for_parent(
                    child_table=member_table,
                    parent_pk_column=owner_pk_column,
                )

                if fk_column is None:
                    fk_column = self.add_fk_column_like_parent_key(
                        child_table=member_table,
                        parent_pk_column=owner_pk_column,
                    )

            self.add_foreign_key_if_missing(
                child_table=member_table,
                child_column=fk_column.name,
                parent_table=owner_table,
                parent_column=owner_pk_column.name,
            )

    def add_foreign_keys_from_matching_primary_keys(
        self,
        tables: list[DB2Table],
        relationship_pairs: dict[tuple[str, str], set[str]],
    ) -> None:
        """
        Generic business-code FK inference.

        Rule:
            If child column base name equals parent PK base name after removing
            trailing four-digit suffix, add FK.

        Important:
            If a detected owner/member relationship already exists between
            parent and child, skip this inference to avoid duplicate generic FK
            columns, especially when multiple sets exist for same pair.
        """

        for child_table in tables:
            for parent_table in tables:
                if child_table.name == parent_table.name:
                    continue

                pair_key = (
                    parent_table.name,
                    child_table.name,
                )

                if pair_key in relationship_pairs:
                    continue

                if not parent_table.primary_key:
                    continue

                parent_pk_column = self.find_column(
                    table=parent_table,
                    column_name=parent_table.primary_key,
                )

                if parent_pk_column is None:
                    continue

                if self.is_technical_key(parent_pk_column.name):
                    continue

                for child_column in child_table.columns:
                    if child_column.primary_key:
                        continue

                    if self.is_technical_key(child_column.name):
                        continue

                    if self.foreign_key_exists(
                        child_table=child_table,
                        child_column=child_column.name,
                        parent_table=parent_table,
                        parent_column=parent_pk_column.name,
                    ):
                        continue

                    if self.columns_have_same_base_name(
                        left=child_column.name,
                        right=parent_pk_column.name,
                    ):
                        self.add_foreign_key_if_missing(
                            child_table=child_table,
                            child_column=child_column.name,
                            parent_table=parent_table,
                            parent_column=parent_pk_column.name,
                        )

    def ensure_owner_primary_key(
        self,
        table: DB2Table,
    ) -> DB2Column | None:
        """
        Ensures an owner table has a primary key.

        If natural PK exists, use it.
        If no PK exists, create generic technical PK:
            <TABLE_NAME>_ID
        """

        if table.primary_key:
            primary_key_column = self.find_column(
                table=table,
                column_name=table.primary_key,
            )

            if primary_key_column is not None:
                primary_key_column.nullable = False
                primary_key_column.primary_key = True
                return primary_key_column

        technical_key_name = self.technical_key_name(
            table_name=table.name,
        )

        existing_technical_key = self.find_column(
            table=table,
            column_name=technical_key_name,
        )

        if existing_technical_key is not None:
            existing_technical_key.nullable = False
            existing_technical_key.primary_key = True
            table.primary_key = existing_technical_key.name
            return existing_technical_key

        technical_key = DB2Column(
            name=technical_key_name,
            datatype=self.TECHNICAL_KEY_DATATYPE,
            nullable=False,
            primary_key=True,
        )

        table.columns.insert(
            0,
            technical_key,
        )

        table.primary_key = technical_key.name

        return technical_key

    def ensure_set_specific_fk_column(
        self,
        child_table: DB2Table,
        set_name: str,
        parent_pk_column: DB2Column,
    ) -> DB2Column:
        """
        Creates or reuses set-specific child FK column.

        Generic format:
            <SET_NAME>_<PARENT_PK>

        Example:
            MANAGES_EMP_ID_0415
            REPORTS_TO_EMP_ID_0415
        """

        column_name = self.normalize_column_name(
            f"{set_name}_{parent_pk_column.name}"
        )

        existing_column = self.find_column(
            table=child_table,
            column_name=column_name,
        )

        if existing_column is not None:
            return existing_column

        new_column = DB2Column(
            name=column_name,
            datatype=parent_pk_column.datatype,
            nullable=True,
            primary_key=False,
        )

        child_table.columns.append(new_column)

        return new_column

    def find_existing_fk_column_for_parent(
        self,
        child_table: DB2Table,
        parent_pk_column: DB2Column,
    ) -> DB2Column | None:
        """
        Finds existing child-side FK column using generic rules only.

        Rule 1:
            Exact parent PK column exists in child.

        Rule 2:
            Child column base name equals parent PK base name after removing
            only trailing four-digit record suffix.
        """

        exact_column = self.find_column(
            table=child_table,
            column_name=parent_pk_column.name,
        )

        if exact_column is not None:
            return exact_column

        for child_column in child_table.columns:
            if child_column.primary_key:
                continue

            if self.columns_have_same_base_name(
                left=child_column.name,
                right=parent_pk_column.name,
            ):
                return child_column

        return None

    def add_fk_column_like_parent_key(
        self,
        child_table: DB2Table,
        parent_pk_column: DB2Column,
    ) -> DB2Column:
        existing_column = self.find_column(
            table=child_table,
            column_name=parent_pk_column.name,
        )

        if existing_column is not None:
            return existing_column

        new_column = DB2Column(
            name=parent_pk_column.name,
            datatype=parent_pk_column.datatype,
            nullable=True,
            primary_key=False,
        )

        child_table.columns.append(new_column)

        return new_column

    def columns_have_same_base_name(
        self,
        left: str | None,
        right: str | None,
    ) -> bool:
        left_base = self.remove_trailing_record_suffix(left)
        right_base = self.remove_trailing_record_suffix(right)

        if not left_base:
            return False

        if not right_base:
            return False

        return left_base == right_base

    def remove_trailing_record_suffix(
        self,
        value: str | None,
    ) -> str:
        """
        Removes only trailing four-digit IDMS suffix.

        Generic examples:
            EMP_ID_0415 -> EMP_ID
            INS_PLAN_CODE_0435 -> INS_PLAN_CODE
            CLAIM_DATE_0405 -> CLAIM_DATE
        """

        normalized = self.normalize_column_name(value)

        return re.sub(
            r"_[0-9]{4}$",
            "",
            normalized,
        )

    def add_foreign_key_if_missing(
        self,
        child_table: DB2Table,
        child_column: str,
        parent_table: DB2Table,
        parent_column: str,
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
            )
        )

    def foreign_key_exists(
        self,
        child_table: DB2Table,
        child_column: str,
        parent_table: DB2Table,
        parent_column: str,
    ) -> bool:
        for existing_fk in child_table.foreign_keys:
            if (
                existing_fk.column_name == child_column
                and existing_fk.reference_table == parent_table.name
                and existing_fk.reference_column == parent_column
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
            if self.normalize_table_name(table.name) == normalized_name:
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

        for column in table.columns:
            if self.normalize_column_name(column.name) == normalized_name:
                return column

        return None

    def technical_key_name(
        self,
        table_name: str,
    ) -> str:
        return f"{self.normalize_table_name(table_name)}_ID"

    def is_technical_key(
        self,
        column_name: str | None,
    ) -> bool:
        normalized = self.normalize_column_name(column_name)

        if not normalized:
            return False

        if re.search(
            r"_[0-9]{4}$",
            normalized,
        ):
            return False

        return normalized.endswith("_ID")

    def normalize_table_name(
        self,
        value: str | None,
    ) -> str:
        normalized = DB2NameNormalizer.normalize_record_name(value)
        return self.to_db2_identifier(normalized)

    def normalize_column_name(
        self,
        value: str | None,
    ) -> str:
        normalized = DB2NameNormalizer.normalize_column_name(value)
        return self.to_db2_identifier(normalized)

    def to_db2_identifier(
        self,
        value: str | None,
    ) -> str:
        if not value:
            return ""

        normalized = str(value).strip().upper()
        normalized = normalized.replace("-", "_")
        normalized = normalized.replace(" ", "_")
        normalized = re.sub(
            r"[^A-Z0-9_]",
            "_",
            normalized,
        )
        normalized = re.sub(
            r"_+",
            "_",
            normalized,
        )

        return normalized.strip("_")

    def get_attr(
        self,
        obj,
        name: str,
    ):
        if obj is None:
            return None

        if hasattr(obj, name):
            return getattr(obj, name)

        if isinstance(obj, dict):
            return obj.get(name)

        return None