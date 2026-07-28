class DDLGenerator:
    def generate(
        self,
        db2_model,
    ) -> str:
        ddl: list[str] = []

        for table in getattr(db2_model, "tables", []) or []:
            ddl.extend(
                self.generate_create_table(
                    table=table,
                )
            )

        foreign_key_statements = self.generate_foreign_key_statements(
            db2_model=db2_model,
        )

        if foreign_key_statements:
            ddl.append("")
            ddl.extend(foreign_key_statements)

        return "\n".join(ddl)

    def generate_create_table(
        self,
        table,
    ) -> list[str]:
        lines: list[str] = []

        table_name = getattr(table, "name", "")

        lines.append(f"CREATE TABLE {table_name}")
        lines.append("(")

        definitions: list[str] = []
        added_columns: set[str] = set()

        for column in getattr(table, "columns", []) or []:
            column_name = getattr(column, "name", "")

            if not column_name:
                continue

            if column_name in added_columns:
                continue

            datatype = getattr(column, "datatype", "")

            definition = f"    {column_name} {datatype}"

            if not getattr(column, "nullable", True):
                definition += " NOT NULL"

            definitions.append(definition)
            added_columns.add(column_name)

        primary_keys = self.primary_key_columns(
            table=table,
        )

        if primary_keys:
            definitions.append(
                f"    PRIMARY KEY ({', '.join(primary_keys)})"
            )

        lines.append(",\n".join(definitions))
        lines.append(");")
        lines.append("")

        return lines

    def primary_key_columns(
        self,
        table,
    ) -> list[str]:
        primary_keys = list(getattr(table, "primary_keys", []) or [])

        if not primary_keys:
            single_primary_key = getattr(table, "primary_key", None)

            if single_primary_key:
                primary_keys = [single_primary_key]

        if not primary_keys:
            primary_keys = [
                getattr(column, "name", "")
                for column in getattr(table, "columns", []) or []
                if getattr(column, "primary_key", False)
            ]

        cleaned_primary_keys = []

        for primary_key in primary_keys:
            if not primary_key:
                continue

            if primary_key in cleaned_primary_keys:
                continue

            cleaned_primary_keys.append(primary_key)

        return cleaned_primary_keys

    def generate_foreign_key_statements(
        self,
        db2_model,
    ) -> list[str]:
        statements: list[str] = []
        added_foreign_keys: set[tuple[str, str, str, str]] = set()

        for table in getattr(db2_model, "tables", []) or []:
            table_name = getattr(table, "name", "")

            if not table_name:
                continue

            for foreign_key in getattr(table, "foreign_keys", []) or []:
                child_column = self.get_foreign_key_column_name(
                    foreign_key=foreign_key,
                )

                parent_table = self.get_foreign_key_reference_table(
                    foreign_key=foreign_key,
                )

                parent_column = self.get_foreign_key_reference_column(
                    foreign_key=foreign_key,
                )

                if not child_column or not parent_table or not parent_column:
                    continue

                fk_key = (
                    table_name,
                    child_column,
                    parent_table,
                    parent_column,
                )

                if fk_key in added_foreign_keys:
                    continue

                added_foreign_keys.add(fk_key)

                constraint_name = self.constraint_name(
                    table_name=table_name,
                    column_name=child_column,
                )

                statements.append(
                    f"ALTER TABLE {table_name} "
                    f"ADD CONSTRAINT {constraint_name} "
                    f"FOREIGN KEY ({child_column}) "
                    f"REFERENCES {parent_table} ({parent_column});"
                )

        return statements

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

    def get_foreign_key_reference_table(
        self,
        foreign_key,
    ) -> str:
        return (
            getattr(foreign_key, "reference_table", None)
            or getattr(foreign_key, "parent_table", None)
            or getattr(foreign_key, "referenced_table", None)
            or ""
        )

    def get_foreign_key_reference_column(
        self,
        foreign_key,
    ) -> str:
        return (
            getattr(foreign_key, "reference_column", None)
            or getattr(foreign_key, "parent_column", None)
            or getattr(foreign_key, "referenced_column", None)
            or getattr(foreign_key, "parent_key", None)
            or ""
        )

    def constraint_name(
        self,
        table_name: str,
        column_name: str,
    ) -> str:
        raw_name = f"FK_{table_name}_{column_name}"

        cleaned = (
            raw_name
            .replace("-", "_")
            .replace(" ", "_")
            .replace(".", "_")
            .upper()
        )

        return cleaned[:128]