class DDLGenerator:
    """
    Generates DB2 DDL.

    Behavior:
    - CREATE TABLE contains columns and primary keys.
    - Foreign keys are emitted as ALTER TABLE statements after all tables.
    - This avoids table creation order issues.
    """

    def generate(
        self,
        db2_model,
    ) -> str:
        ddl: list[str] = []

        for table in db2_model.tables:
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

        lines.append(f"CREATE TABLE {table.name}")
        lines.append("(")

        definitions: list[str] = []
        added_columns: set[str] = set()

        for column in table.columns:
            if column.name in added_columns:
                continue

            definition = f"    {column.name} {column.datatype}"

            if not column.nullable:
                definition += " NOT NULL"

            definitions.append(definition)
            added_columns.add(column.name)

        if table.primary_key:
            definitions.append(
                f"    PRIMARY KEY ({table.primary_key})"
            )

        lines.append(",\n".join(definitions))
        lines.append(");")
        lines.append("")

        return lines

    def generate_foreign_key_statements(
        self,
        db2_model,
    ) -> list[str]:
        statements: list[str] = []
        added_foreign_keys: set[tuple[str, str, str, str]] = set()

        for table in db2_model.tables:
            for fk in table.foreign_keys:
                fk_key = (
                    table.name,
                    fk.column_name,
                    fk.reference_table,
                    fk.reference_column,
                )

                if fk_key in added_foreign_keys:
                    continue

                statements.append(
                    "ALTER TABLE "
                    f"{table.name} "
                    "ADD FOREIGN KEY "
                    f"({fk.column_name}) "
                    "REFERENCES "
                    f"{fk.reference_table} "
                    f"({fk.reference_column});"
                )

                added_foreign_keys.add(fk_key)

        return statements