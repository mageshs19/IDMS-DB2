import re

from idms_db2_converter.exceptions import ConversionError
from idms_db2_converter.models import (
    Column,
    Record,
    Relationship,
    SchemaModel
)


class DDLParser:
    """
    Robust DB2 DDL parser for Phase 2.

    This version uses manual datatype parsing instead of fragile regex-only
    datatype parsing.

    Fixes:
    - VARCHAR(3) being skipped
    - VARCHAR(45) being skipped
    - CHAR(1) being skipped
    - DECIMAL(18,0) being skipped
    - Missing columns in final Phase 2 schema
    """

    DEBUG = True

    INLINE_PRIMARY_KEY = re.compile(
        r"\bPRIMARY\s+KEY\b",
        re.IGNORECASE
    )

    INLINE_NOT_NULL = re.compile(
        r"\bNOT\s+NULL\b",
        re.IGNORECASE
    )

    TABLE_PRIMARY_KEY = re.compile(
        r"\bPRIMARY\s+KEY\s*$(?P<columns>.*?)$",
        re.IGNORECASE | re.DOTALL
    )

    TABLE_FOREIGN_KEY = re.compile(
        r"""
        \bFOREIGN\s+KEY\s*
        $(?P<child_cols>.*?)$
        \s+REFERENCES\s+
        (?P<parent_table>(?:[A-Z0-9_]+\.)?[A-Z0-9_]+)
        \s*
        $(?P<parent_cols>.*?)$
        """,
        re.IGNORECASE | re.DOTALL | re.VERBOSE
    )

    ALTER_TABLE_FK = re.compile(
        r"""
        \bALTER\s+TABLE\s+
        (?P<child_table>(?:[A-Z0-9_]+\.)?[A-Z0-9_]+)
        .*?
        \bFOREIGN\s+KEY\s*
        $(?P<child_cols>.*?)$
        \s+REFERENCES\s+
        (?P<parent_table>(?:[A-Z0-9_]+\.)?[A-Z0-9_]+)
        \s*
        $(?P<parent_cols>.*?)$
        """,
        re.IGNORECASE | re.DOTALL | re.VERBOSE
    )

    CONSTRAINT_STARTERS = {
        "CONSTRAINT",
        "PRIMARY",
        "FOREIGN",
        "UNIQUE",
        "CHECK"
    }

    def parse(
        self,
        ddl: str
    ) -> SchemaModel:

        self._debug(
            "USING DDL_PARSER VERSION MANUAL-DATATYPE-2026-07-01"
        )

        schema = SchemaModel()
        schema.schema_source = "DDL"

        if ddl is None:
            ddl = ""

        self._debug(
            f"DDL INPUT LENGTH: {len(ddl)}"
        )

        self._debug(
            f"DDL HAS CREATE TABLE: {'CREATE TABLE' in ddl.upper()}"
        )

        ddl = self.remove_comments(
            ddl
        )

        create_statements = self._extract_create_table_statements(
            ddl
        )

        self._debug(
            f"DDL PARSER CREATE TABLE COUNT: {len(create_statements)}"
        )

        for statement in create_statements:
            table_name = statement["table_name"]
            body = statement["body"]

            self._debug(
                f"DDL PARSER START TABLE: {table_name}"
            )

            record = Record(
                name=table_name,
                primary_key=None,
                fields={}
            )

            schema.record_table_map[
                table_name
            ] = table_name

            entries = self.split_entries(
                body
            )

            self._debug(
                f"DDL PARSER TABLE {table_name} ENTRY COUNT: {len(entries)}"
            )

            pending_foreign_keys: list[dict] = []

            for entry in entries:
                entry = entry.strip()

                if not entry:
                    continue

                first_word = self._first_word(
                    entry
                )

                if first_word in self.CONSTRAINT_STARTERS:
                    self._parse_constraint_entry(
                        record=record,
                        entry=entry,
                        pending_foreign_keys=pending_foreign_keys
                    )
                    continue

                column = self._parse_column_entry(
                    entry=entry,
                    table_name=table_name
                )

                if column is None:
                    continue

                record.fields[
                    column.name
                ] = column

                if self.INLINE_PRIMARY_KEY.search(entry):
                    record.primary_key = column.name
                    column.nullable = False

            schema.records[
                table_name
            ] = record

            self._debug(
                f"DDL PARSER TABLE {table_name}: "
                f"{len(record.fields)} columns, PK={record.primary_key}"
            )

            for field_name, field in record.fields.items():
                self._debug(
                    f"  COLUMN {field_name}: "
                    f"{field.datatype}({field.length},{field.scale}) "
                    f"NULLABLE={field.nullable}"
                )

            for foreign_key in pending_foreign_keys:
                self._add_relationship(
                    schema=schema,
                    child_table=table_name,
                    child_fk=foreign_key["child_fk"],
                    parent_table=foreign_key["parent_table"],
                    parent_key=foreign_key["parent_key"]
                )

        self._parse_alter_table_foreign_keys(
            ddl=ddl,
            schema=schema
        )

        self._validate(
            schema
        )

        if "CREATE TABLE" in ddl.upper() and not schema.records:
            raise ConversionError(
                "DDL text was provided and contains CREATE TABLE, but no tables were parsed."
            )

        return schema

    def remove_comments(
        self,
        ddl: str
    ) -> str:

        ddl = re.sub(
            r"--.*?$",
            "",
            ddl,
            flags=re.MULTILINE
        )

        ddl = re.sub(
            r"/\*.*?\*/",
            "",
            ddl,
            flags=re.DOTALL
        )

        return ddl

    def _extract_create_table_statements(
        self,
        ddl: str
    ) -> list[dict]:

        results: list[dict] = []

        pattern = re.compile(
            r"\bCREATE\s+TABLE\s+(?P<table>(?:[A-Z0-9_]+\.)?[A-Z0-9_]+)",
            re.IGNORECASE
        )

        for match in pattern.finditer(ddl):
            table_name = self._normalize_name(
                match.group("table")
            )

            open_index = ddl.find(
                "(",
                match.end()
            )

            if open_index < 0:
                self._debug(
                    f"DDL PARSER TABLE {table_name}: no opening parenthesis found"
                )
                continue

            close_index = self._find_matching_parenthesis(
                text=ddl,
                open_index=open_index
            )

            if close_index < 0:
                self._debug(
                    f"DDL PARSER TABLE {table_name}: no closing parenthesis found"
                )
                continue

            body = ddl[
                open_index + 1:close_index
            ]

            results.append(
                {
                    "table_name": table_name,
                    "body": body
                }
            )

        return results

    def _find_matching_parenthesis(
        self,
        text: str,
        open_index: int
    ) -> int:

        depth = 0
        quote = None

        for index in range(open_index, len(text)):
            char = text[index]

            if quote:
                if char == quote:
                    quote = None
                continue

            if char in {
                "'",
                '"'
            }:
                quote = char
                continue

            if char == "(":
                depth += 1
                continue

            if char == ")":
                depth -= 1

                if depth == 0:
                    return index

        return -1

    def split_entries(
        self,
        body: str
    ) -> list[str]:

        entries: list[str] = []
        current: list[str] = []
        depth = 0
        quote = None

        for char in body:
            if quote:
                current.append(char)

                if char == quote:
                    quote = None

                continue

            if char in {
                "'",
                '"'
            }:
                quote = char
                current.append(char)
                continue

            if char == "(":
                depth += 1
                current.append(char)
                continue

            if char == ")":
                depth -= 1
                current.append(char)
                continue

            if char == "," and depth == 0:
                entry = "".join(current).strip()

                if entry:
                    entries.append(entry)

                current = []
                continue

            current.append(char)

        entry = "".join(current).strip()

        if entry:
            entries.append(entry)

        return entries

    def _parse_constraint_entry(
        self,
        record: Record,
        entry: str,
        pending_foreign_keys: list[dict]
    ) -> None:

        primary_key_match = self.TABLE_PRIMARY_KEY.search(
            entry
        )

        if primary_key_match:
            primary_key = self._first_column(
                primary_key_match.group("columns")
            )

            if primary_key:
                record.primary_key = primary_key

                if primary_key in record.fields:
                    record.fields[
                        primary_key
                    ].nullable = False

            self._debug(
                f"DDL PARSER PRIMARY KEY FOR {record.name}: {record.primary_key}"
            )

            return

        foreign_key_match = self.TABLE_FOREIGN_KEY.search(
            entry
        )

        if foreign_key_match:
            child_fk = self._first_column(
                foreign_key_match.group("child_cols")
            )

            parent_table = self._normalize_name(
                foreign_key_match.group("parent_table")
            )

            parent_key = self._first_column(
                foreign_key_match.group("parent_cols")
            )

            if child_fk and parent_table and parent_key:
                pending_foreign_keys.append(
                    {
                        "child_fk": child_fk,
                        "parent_table": parent_table,
                        "parent_key": parent_key
                    }
                )

                self._debug(
                    f"DDL PARSER FK: {child_fk} -> {parent_table}({parent_key})"
                )

            return

    def _parse_alter_table_foreign_keys(
        self,
        ddl: str,
        schema: SchemaModel
    ) -> None:

        for match in self.ALTER_TABLE_FK.finditer(ddl):
            child_table = self._normalize_name(
                match.group("child_table")
            )

            child_fk = self._first_column(
                match.group("child_cols")
            )

            parent_table = self._normalize_name(
                match.group("parent_table")
            )

            parent_key = self._first_column(
                match.group("parent_cols")
            )

            if not child_table:
                continue

            if not child_fk:
                continue

            if not parent_table:
                continue

            if not parent_key:
                continue

            self._add_relationship(
                schema=schema,
                child_table=child_table,
                child_fk=child_fk,
                parent_table=parent_table,
                parent_key=parent_key
            )

    def _add_relationship(
        self,
        schema: SchemaModel,
        child_table: str,
        child_fk: str,
        parent_table: str,
        parent_key: str
    ) -> None:

        child_table = self._normalize_name(child_table)
        child_fk = self._normalize_name(child_fk)
        parent_table = self._normalize_name(parent_table)
        parent_key = self._normalize_name(parent_key)

        set_name = f"{parent_table}-{child_table}"

        schema.relationships[set_name] = Relationship(
            set_name=set_name,
            parent_record=parent_table,
            child_record=child_table,
            cardinality="1:N",
            parent_key=parent_key,
            child_fk=child_fk,
            order_by=[child_fk]
        )

    def _parse_column_entry(
        self,
        entry: str,
        table_name: str
    ) -> Column | None:

        entry = entry.strip()

        if not entry:
            return None

        match = re.match(
            r"^(?P<name>[A-Z0-9_]+)\s+(?P<datatype>.+)$",
            entry,
            flags=re.IGNORECASE | re.DOTALL
        )

        if not match:
            self._debug(
                f"DDL PARSER SKIPPED ENTRY IN {table_name}: no column match. ENTRY={repr(entry)}"
            )
            return None

        column_name = self._normalize_name(
            match.group("name")
        )

        datatype_text = match.group("datatype").strip()

        datatype, length, scale = self._parse_datatype(
            datatype_text
        )

        if datatype is None:
            self._debug_unrecognized_datatype(
                table_name=table_name,
                column_name=column_name,
                datatype_text=datatype_text
            )
            return None

        nullable = not bool(
            self.INLINE_NOT_NULL.search(entry)
        )

        return Column(
            name=column_name,
            datatype=datatype,
            length=length,
            scale=scale,
            nullable=nullable
        )

    def _parse_datatype(
        self,
        datatype_text: str
    ) -> tuple[str | None, int | None, int | None]:

        text = self._normalize_datatype_text(
            datatype_text
        )

        if not text:
            return (
                None,
                None,
                None
            )

        datatype_name = self._leading_word(
            text
        )

        if datatype_name in {
            "VARCHAR",
            "CHAR",
            "CHARACTER"
        }:
            length = self._manual_first_parenthesized_int(
                text
            )

            if datatype_name == "CHARACTER":
                datatype_name = "CHAR"

            if length is None and datatype_name == "CHAR":
                length = 1

            if length is not None:
                return (
                    datatype_name,
                    length,
                    None
                )

        if datatype_name in {
            "DECIMAL",
            "NUMERIC"
        }:
            precision_scale = self._manual_precision_scale(
                text
            )

            if precision_scale is not None:
                precision, scale = precision_scale

                return (
                    "DECIMAL",
                    precision,
                    scale
                )

        if datatype_name == "SMALLINT":
            return (
                "SMALLINT",
                4,
                0
            )

        if datatype_name in {
            "INTEGER",
            "INT"
        }:
            return (
                "INTEGER",
                9,
                0
            )

        if datatype_name == "BIGINT":
            return (
                "BIGINT",
                18,
                0
            )

        if datatype_name == "DATE":
            return (
                "DATE",
                None,
                None
            )

        if datatype_name == "TIMESTAMP":
            return (
                "TIMESTAMP",
                None,
                None
            )

        if datatype_name == "TIME":
            return (
                "TIME",
                None,
                None
            )

        return (
            None,
            None,
            None
        )

    def _normalize_datatype_text(
        self,
        datatype_text: str
    ) -> str:

        text = datatype_text or ""

        text = str(text).strip().upper()

        text = text.replace("（", "(")
        text = text.replace("）", ")")
        text = text.replace("，", ",")
        text = text.replace("\u00a0", " ")

        text = re.sub(
            r"\s+",
            " ",
            text
        )

        text = re.sub(
            r"\bNOT\s+NULL\b",
            "",
            text,
            flags=re.IGNORECASE
        )

        text = re.sub(
            r"\bPRIMARY\s+KEY\b",
            "",
            text,
            flags=re.IGNORECASE
        )

        text = re.sub(
            r"\bDEFAULT\b.*$",
            "",
            text,
            flags=re.IGNORECASE
        )

        return text.strip()

    def _leading_word(
        self,
        text: str
    ) -> str:

        result = []

        for char in text:
            if char.isalpha():
                result.append(char)
                continue

            break

        return "".join(result).upper()

    def _manual_first_parenthesized_int(
        self,
        text: str
    ) -> int | None:

        open_index = text.find("(")

        if open_index < 0:
            return None

        close_index = text.find(")", open_index + 1)

        if close_index < 0:
            return None

        content = text[
            open_index + 1:close_index
        ].strip()

        if not content.isdigit():
            return None

        return int(content)

    def _manual_precision_scale(
        self,
        text: str
    ) -> tuple[int, int] | None:

        open_index = text.find("(")

        if open_index < 0:
            return None

        close_index = text.find(")", open_index + 1)

        if close_index < 0:
            return None

        content = text[
            open_index + 1:close_index
        ].strip()

        parts = [
            part.strip()
            for part in content.split(",")
        ]

        if len(parts) != 2:
            return None

        if not parts[0].isdigit():
            return None

        if not parts[1].isdigit():
            return None

        return (
            int(parts[0]),
            int(parts[1])
        )

    def _validate(
        self,
        schema: SchemaModel
    ) -> None:

        errors: list[str] = []

        for record in schema.records.values():
            if record.primary_key and record.primary_key not in record.fields:
                errors.append(
                    f"{record.name} primary key {record.primary_key} is not declared as a column."
                )

            for field_name, field in record.fields.items():
                if not field.datatype:
                    errors.append(
                        f"{record.name}.{field_name} has no datatype."
                    )

        if errors:
            raise ConversionError(
                "\n".join(errors)
            )

    def _first_word(
        self,
        entry: str
    ) -> str:

        tokens = entry.strip().split()

        if not tokens:
            return ""

        return self._normalize_name(
            tokens[0]
        )

    def _first_column(
        self,
        text: str
    ) -> str | None:

        if not text:
            return None

        first = text.split(",")[0].strip()

        if not first:
            return None

        return self._normalize_name(
            first
        )

    def _normalize_name(
        self,
        value: str | None
    ) -> str:

        if not value:
            return ""

        value = str(value).strip()
        value = value.strip('"')
        value = value.strip("'")
        value = value.strip("`")
        value = value.strip("[")
        value = value.strip("]")

        if "." in value:
            value = value.split(".")[-1]

        return value.upper()

    def _debug(
        self,
        message: str
    ) -> None:

        if self.DEBUG:
            print(message)

    def _debug_unrecognized_datatype(
        self,
        table_name: str,
        column_name: str,
        datatype_text: str
    ) -> None:

        if not self.DEBUG:
            return

        normalized = self._normalize_datatype_text(
            datatype_text
        )

        char_codes = [
            ord(char)
            for char in datatype_text
        ]

        print(
            "DDL PARSER SKIPPED COLUMN "
            f"{table_name}.{column_name}: "
            f"raw={repr(datatype_text)} "
            f"normalized={repr(normalized)} "
            f"leading={repr(self._leading_word(normalized))} "
            f"char_codes={char_codes}"
        )