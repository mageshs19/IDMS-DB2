import re

from idms_db2_converter.exceptions import ConversionError
from idms_db2_converter.models import (
    Column,
    Record,
    Relationship,
    SchemaModel,
)


class DDLParser:
    """
    Robust DB2 DDL parser for Phase 2.

    Supports:
    - CREATE TABLE with table name and opening parenthesis on separate lines.
    - CREATE TABLE with blank lines before opening parenthesis.
    - CHAR(n), VARCHAR(n), DECIMAL(p), DECIMAL(p,s).
    - DATE, TIME, TIMESTAMP.
    - Composite primary keys.
    - Composite foreign keys.
    - ALTER TABLE ADD FOREIGN KEY.
    - Schema-qualified table names.
    - Quoted identifiers.

    Schema Listing datatype rule:
    - SMALLINT, INTEGER, BIGINT are normalized to DECIMAL equivalents.
    - CHAR(n), VARCHAR(n), DECIMAL(p,s) must preserve length/precision/scale.
    """

    DEBUG = True

    CONSTRAINT_STARTERS = {
        "CONSTRAINT",
        "PRIMARY",
        "FOREIGN",
        "UNIQUE",
        "CHECK",
    }

    INLINE_PRIMARY_KEY = re.compile(
        r"\bPRIMARY\s+KEY\b",
        re.IGNORECASE,
    )

    INLINE_NOT_NULL = re.compile(
        r"\bNOT\s+NULL\b",
        re.IGNORECASE,
    )

    TABLE_PRIMARY_KEY = re.compile(
        r"\bPRIMARY\s+KEY\s*$(?P<columns>.*?)$",
        re.IGNORECASE | re.DOTALL,
    )

    TABLE_FOREIGN_KEY = re.compile(
        r"""
        \bFOREIGN\s+KEY\s*
        $(?P<child_cols>.*?)$
        \s+REFERENCES\s+
        (?P<parent_table>(?:"[^"]+"|[A-Z0-9_]+)(?:\.(?:"[^"]+"|[A-Z0-9_]+))?)
        \s*
        $(?P<parent_cols>.*?)$
        """,
        re.IGNORECASE | re.DOTALL | re.VERBOSE,
    )

    ALTER_TABLE_FK = re.compile(
        r"""
        \bALTER\s+TABLE\s+
        (?P<child_table>(?:"[^"]+"|[A-Z0-9_]+)(?:\.(?:"[^"]+"|[A-Z0-9_]+))?)
        .*?
        \bFOREIGN\s+KEY\s*
        $(?P<child_cols>.*?)$
        \s+REFERENCES\s+
        (?P<parent_table>(?:"[^"]+"|[A-Z0-9_]+)(?:\.(?:"[^"]+"|[A-Z0-9_]+))?)
        \s*
        $(?P<parent_cols>.*?)$
        """,
        re.IGNORECASE | re.DOTALL | re.VERBOSE,
    )

    def parse(
        self,
        ddl: str,
    ) -> SchemaModel:
        self._debug(
            "USING DDL_PARSER VERSION FIXED-DATATYPE-PARENS-COMPOSITE-2026-08-05"
        )

        schema = SchemaModel()
        schema.schema_source = "DDL"

        if ddl is None:
            ddl = ""

        self._debug(
            f"DDL INPUT LENGTH: {len(ddl)}"
        )

        ddl = self.remove_comments(
            ddl=ddl,
        )

        create_statements = self._extract_create_table_statements(
            ddl=ddl,
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
                primary_keys=[],
                fields={},
            )

            schema.record_table_map[table_name] = table_name

            pending_foreign_keys = []

            entries = self.split_entries(
                body=body,
            )

            self._debug(
                f"DDL PARSER TABLE {table_name} ENTRY COUNT: {len(entries)}"
            )

            for entry in entries:
                entry = entry.strip()

                if not entry:
                    continue

                first_word = self._first_word(
                    entry=entry,
                )

                if first_word in self.CONSTRAINT_STARTERS:
                    self._parse_constraint_entry(
                        record=record,
                        entry=entry,
                        pending_foreign_keys=pending_foreign_keys,
                    )
                    continue

                column = self._parse_column_entry(
                    entry=entry,
                    table_name=table_name,
                )

                if column is None:
                    continue

                record.fields[column.name] = column

                if self.INLINE_PRIMARY_KEY.search(entry):
                    self._set_primary_keys(
                        record=record,
                        primary_keys=[column.name],
                    )

            schema.records[table_name] = record

            for foreign_key in pending_foreign_keys:
                self._add_relationship(
                    schema=schema,
                    child_table=table_name,
                    child_fks=foreign_key["child_fks"],
                    parent_table=foreign_key["parent_table"],
                    parent_keys=foreign_key["parent_keys"],
                )

            self._debug_record(
                record=record,
            )

        self._parse_alter_table_foreign_keys(
            ddl=ddl,
            schema=schema,
        )

        self._validate(
            schema=schema,
        )

        if "CREATE TABLE" in ddl.upper() and not schema.records:
            raise ConversionError(
                "DDL text was provided and contains CREATE TABLE, but no tables were parsed."
            )

        return schema

    def remove_comments(
        self,
        ddl: str,
    ) -> str:
        ddl = re.sub(
            r"--.*?$",
            "",
            ddl,
            flags=re.MULTILINE,
        )

        ddl = re.sub(
            r"/\*.*?\*/",
            "",
            ddl,
            flags=re.DOTALL,
        )

        return ddl

    def _extract_create_table_statements(
        self,
        ddl: str,
    ) -> list[dict[str, str]]:
        statements = []
        upper = ddl.upper()
        marker = "CREATE TABLE"
        position = 0

        while True:
            start = upper.find(
                marker,
                position,
            )

            if start < 0:
                break

            name_start = start + len(marker)

            while name_start < len(ddl) and ddl[name_start].isspace():
                name_start += 1

            if name_start >= len(ddl):
                break

            table_name, name_end = self._read_identifier(
                text=ddl,
                start=name_start,
            )

            table_name = self._normalize_name(
                table_name,
            )

            if not table_name:
                position = name_start + 1
                continue

            open_index = ddl.find(
                "(",
                name_end,
            )

            if open_index < 0:
                position = name_end
                continue

            close_index = self._find_matching_parenthesis(
                text=ddl,
                open_index=open_index,
            )

            if close_index is None:
                raise ConversionError(
                    f"CREATE TABLE {table_name} has no matching closing parenthesis."
                )

            body = ddl[open_index + 1 : close_index]

            statements.append(
                {
                    "table_name": table_name,
                    "body": body,
                }
            )

            position = close_index + 1

        return statements

    def _read_identifier(
        self,
        text: str,
        start: int,
    ) -> tuple[str, int]:
        if start >= len(text):
            return "", start

        if text[start] == '"':
            end = start + 1

            while end < len(text):
                if text[end] == '"':
                    return text[start : end + 1], end + 1

                end += 1

            return text[start:], len(text)

        end = start

        while end < len(text):
            char = text[end]

            if char.isspace() or char == "(":
                break

            end += 1

        return text[start:end], end

    def _find_matching_parenthesis(
        self,
        text: str,
        open_index: int,
    ) -> int | None:
        depth = 0
        in_single_quote = False
        in_double_quote = False

        for index in range(open_index, len(text)):
            char = text[index]

            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
                continue

            if char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
                continue

            if in_single_quote or in_double_quote:
                continue

            if char == "(":
                depth += 1
                continue

            if char == ")":
                depth -= 1

                if depth == 0:
                    return index

        return None

    def split_entries(
        self,
        body: str,
    ) -> list[str]:
        entries = []
        current = []
        depth = 0
        in_single_quote = False
        in_double_quote = False

        for char in body:
            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
                current.append(char)
                continue

            if char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
                current.append(char)
                continue

            if not in_single_quote and not in_double_quote:
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
        pending_foreign_keys: list[dict],
    ) -> None:
        normalized_entry = self._remove_constraint_name(
            entry=entry,
        )

        primary_key_match = self.TABLE_PRIMARY_KEY.search(
            normalized_entry,
        )

        if primary_key_match:
            primary_keys = self._column_list(
                primary_key_match.group("columns"),
            )

            if primary_keys:
                self._set_primary_keys(
                    record=record,
                    primary_keys=primary_keys,
                )

            return

        foreign_key_match = self.TABLE_FOREIGN_KEY.search(
            normalized_entry,
        )

        if foreign_key_match:
            child_fks = self._column_list(
                foreign_key_match.group("child_cols"),
            )

            parent_table = self._normalize_name(
                foreign_key_match.group("parent_table"),
            )

            parent_keys = self._column_list(
                foreign_key_match.group("parent_cols"),
            )

            if child_fks and parent_table and parent_keys:
                self._validate_key_pairing(
                    context=f"FK in table {record.name}",
                    child_fks=child_fks,
                    parent_keys=parent_keys,
                )

                pending_foreign_keys.append(
                    {
                        "child_fks": child_fks,
                        "parent_table": parent_table,
                        "parent_keys": parent_keys,
                    }
                )

            return

    def _remove_constraint_name(
        self,
        entry: str,
    ) -> str:
        tokens = entry.strip().split()

        if len(tokens) >= 3 and tokens[0].upper() == "CONSTRAINT":
            return " ".join(tokens[2:])

        return entry

    def _parse_column_entry(
        self,
        entry: str,
        table_name: str,
    ) -> Column | None:
        entry = entry.strip()

        if not entry:
            return None

        match = re.match(
            r'^(?P<name>"[^"]+"|[A-Z0-9_]+)\s+(?P<datatype>.+)$',
            entry,
            flags=re.IGNORECASE | re.DOTALL,
        )

        if not match:
            self._debug(
                f"DDL PARSER SKIPPED ENTRY IN {table_name}: no column match. ENTRY={repr(entry)}"
            )
            return None

        column_name = self._normalize_name(
            match.group("name"),
        )

        datatype_text = match.group("datatype").strip()

        datatype, length, scale = self._parse_datatype(
            datatype_text,
        )

        if not datatype:
            self._debug_unrecognized_datatype(
                table_name=table_name,
                column_name=column_name,
                datatype_text=datatype_text,
            )
            return None

        nullable = not bool(
            self.INLINE_NOT_NULL.search(entry)
            or self.INLINE_PRIMARY_KEY.search(entry)
        )

        primary_key = bool(
            self.INLINE_PRIMARY_KEY.search(entry)
        )

        return Column(
            name=column_name,
            datatype=datatype,
            length=length,
            scale=scale,
            nullable=nullable,
            primary_key=primary_key,
        )

    def _parse_datatype(
        self,
        text: str,
    ) -> tuple[str | None, int | None, int | None]:
        normalized = self._normalize_datatype_text(
            text,
        )

        if not normalized:
            return None, None, None

        leading = self._leading_word(
            normalized,
        )

        if leading in {"CHAR", "CHARACTER"}:
            length = self._first_parenthesized_int(
                normalized,
            )

            if length is None:
                length = 1

            return "CHAR", length, None

        if leading in {"VARCHAR", "VARCHAR2"}:
            length = self._first_parenthesized_int(
                normalized,
            )

            if length is None:
                length = 255

            return "VARCHAR", length, None

        if normalized.startswith("LONG VARCHAR"):
            length = self._first_parenthesized_int(
                normalized,
            )

            if length is None:
                length = 255

            return "VARCHAR", length, None

        if leading in {"DECIMAL", "NUMERIC", "DEC"}:
            precision, scale = self._first_parenthesized_pair(
                normalized,
            )

            if precision is None:
                precision = 18

            if scale is None:
                scale = 0

            return "DECIMAL", precision, scale

        if leading in {"INTEGER", "INT"}:
            return "DECIMAL", 9, 0

        if leading == "BIGINT":
            return "DECIMAL", 18, 0

        if leading == "SMALLINT":
            return "DECIMAL", 4, 0

        if leading == "DATE":
            return "DATE", None, None

        if leading == "TIMESTAMP":
            return "TIMESTAMP", None, None

        if leading == "TIME":
            return "TIME", None, None

        if leading in {"DOUBLE", "FLOAT", "REAL"}:
            return leading, None, None

        return None, None, None

    def _first_parenthesized_int(
        self,
        text: str,
    ) -> int | None:
        value = str(text or "")

        open_index = value.find("(")

        if open_index < 0:
            return None

        close_index = value.find(")", open_index + 1)

        if close_index < 0:
            return None

        content = value[open_index + 1 : close_index].strip()

        if "," in content:
            content = content.split(",", 1)[0].strip()

        if not content.isdigit():
            return None

        return int(content)

    def _first_parenthesized_pair(
        self,
        text: str,
    ) -> tuple[int | None, int | None]:
        value = str(text or "")

        open_index = value.find("(")

        if open_index < 0:
            return None, None

        close_index = value.find(")", open_index + 1)

        if close_index < 0:
            return None, None

        content = value[open_index + 1 : close_index].strip()

        if not content:
            return None, None

        parts = [
            part.strip()
            for part in content.split(",")
        ]

        if not parts:
            return None, None

        if not parts[0].isdigit():
            return None, None

        precision = int(parts[0])
        scale = None

        if len(parts) > 1 and parts[1].isdigit():
            scale = int(parts[1])

        return precision, scale

    def _normalize_datatype_text(
        self,
        text: str,
    ) -> str:
        value = str(text or "").strip().upper()

        stop_patterns = [
            r"\bNOT\s+NULL\b",
            r"\bNULL\b",
            r"\bPRIMARY\s+KEY\b",
            r"\bGENERATED\b",
            r"\bDEFAULT\b",
            r"\bCONSTRAINT\b",
            r"\bREFERENCES\b",
            r"\bCHECK\b",
            r"\bUNIQUE\b",
        ]

        stop_positions = []

        for pattern in stop_patterns:
            match = re.search(
                pattern,
                value,
                flags=re.IGNORECASE,
            )

            if match:
                stop_positions.append(
                    match.start(),
                )

        if stop_positions:
            value = value[: min(stop_positions)].strip()

        value = re.sub(
            r"\s+",
            " ",
            value,
        )

        return value

    def _leading_word(
        self,
        text: str,
    ) -> str:
        match = re.match(
            r"([A-Z0-9]+)",
            text.strip().upper(),
        )

        if not match:
            return ""

        return match.group(1)

    def _parse_alter_table_foreign_keys(
        self,
        ddl: str,
        schema: SchemaModel,
    ) -> None:
        for match in self.ALTER_TABLE_FK.finditer(ddl):
            child_table = self._normalize_name(
                match.group("child_table"),
            )

            child_fks = self._column_list(
                match.group("child_cols"),
            )

            parent_table = self._normalize_name(
                match.group("parent_table"),
            )

            parent_keys = self._column_list(
                match.group("parent_cols"),
            )

            if not child_table:
                continue

            if child_table not in schema.records:
                continue

            if not parent_table or parent_table not in schema.records:
                continue

            if not child_fks or not parent_keys:
                continue

            self._validate_key_pairing(
                context=f"ALTER TABLE FK {child_table} -> {parent_table}",
                child_fks=child_fks,
                parent_keys=parent_keys,
            )

            self._add_relationship(
                schema=schema,
                child_table=child_table,
                child_fks=child_fks,
                parent_table=parent_table,
                parent_keys=parent_keys,
            )

    def _add_relationship(
        self,
        schema: SchemaModel,
        child_table: str,
        child_fks: list[str],
        parent_table: str,
        parent_keys: list[str],
    ) -> None:
        if child_table not in schema.records:
            raise ConversionError(
                f"FK child table {child_table} is not present in schema."
            )

        if parent_table not in schema.records:
            raise ConversionError(
                f"FK parent table {parent_table} is not present in schema."
            )

        self._validate_key_pairing(
            context=f"FK {child_table} -> {parent_table}",
            child_fks=child_fks,
            parent_keys=parent_keys,
        )

        child = schema.records[child_table]
        parent = schema.records[parent_table]

        for child_fk in child_fks:
            if child_fk not in child.fields:
                raise ConversionError(
                    f"FK column {child_table}.{child_fk} is not declared as a column."
                )

        for parent_key in parent_keys:
            if parent_key not in parent.fields:
                raise ConversionError(
                    f"Referenced column {parent_table}.{parent_key} is not declared as a column."
                )

        if parent_keys and not getattr(parent, "primary_keys", []):
            self._set_primary_keys(
                record=parent,
                primary_keys=parent_keys,
            )

        set_name = f"{parent_table}_{child_table}"

        schema.relationships[set_name] = Relationship(
            set_name=set_name,
            parent_record=parent_table,
            child_record=child_table,
            cardinality="1:N",
            parent_key=parent_keys[0] if parent_keys else None,
            child_fk=child_fks[0] if child_fks else None,
            parent_keys=parent_keys,
            child_fks=child_fks,
            order_by=child_fks.copy(),
        )

    def _set_primary_keys(
        self,
        record: Record,
        primary_keys: list[str],
    ) -> None:
        cleaned = []

        for key in primary_keys or []:
            normalized = self._normalize_name(
                key,
            )

            if not normalized:
                continue

            if normalized in cleaned:
                continue

            cleaned.append(
                normalized,
            )

        if hasattr(record, "set_primary_keys"):
            record.set_primary_keys(
                keys=cleaned,
            )
        else:
            record.primary_keys = cleaned
            record.primary_key = cleaned[0] if cleaned else None

        for key in cleaned:
            if key in record.fields:
                record.fields[key].primary_key = True
                record.fields[key].nullable = False

    def _validate_key_pairing(
        self,
        context: str,
        child_fks: list[str],
        parent_keys: list[str],
    ) -> None:
        if len(child_fks) != len(parent_keys):
            raise ConversionError(
                f"{context} has mismatched composite key column counts: "
                f"{len(child_fks)} child FK column(s), "
                f"{len(parent_keys)} parent key column(s)."
            )

    def _column_list(
        self,
        text: str,
    ) -> list[str]:
        if not text:
            return []

        result = []

        for item in text.split(","):
            normalized = self._normalize_name(
                item,
            )

            if not normalized:
                continue

            if normalized in result:
                continue

            result.append(
                normalized,
            )

        return result

    def _validate(
        self,
        schema: SchemaModel,
    ) -> None:
        errors = []

        for record in schema.records.values():
            primary_keys = []

            if hasattr(record, "effective_primary_keys"):
                primary_keys = record.effective_primary_keys()
            else:
                primary_keys = list(getattr(record, "primary_keys", []) or [])

                if getattr(record, "primary_key", None):
                    if record.primary_key not in primary_keys:
                        primary_keys.append(record.primary_key)

            for primary_key in primary_keys:
                if primary_key not in record.fields:
                    errors.append(
                        f"{record.name} primary key {primary_key} is not declared as a column."
                    )

            for field_name, field in record.fields.items():
                if not field.datatype:
                    errors.append(
                        f"{record.name}.{field_name} has no datatype."
                    )

        if errors:
            raise ConversionError(
                "\n".join(errors),
            )

    def _first_word(
        self,
        entry: str,
    ) -> str:
        tokens = entry.strip().split()

        if not tokens:
            return ""

        return self._normalize_name(
            tokens[0],
        )

    def _normalize_name(
        self,
        value: str | None,
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

        value = value.upper()
        value = value.replace("-", "_")
        value = re.sub(
            r"[^A-Z0-9_]",
            "_",
            value,
        )
        value = re.sub(
            r"_+",
            "_",
            value,
        )

        return value.strip("_")

    def _debug(
        self,
        message: str,
    ) -> None:
        if self.DEBUG:
            print(message)

    def _debug_record(
        self,
        record: Record,
    ) -> None:
        if not self.DEBUG:
            return

        primary_keys = list(getattr(record, "primary_keys", []) or [])

        if not primary_keys and getattr(record, "primary_key", None):
            primary_keys = [record.primary_key]

        print(
            f"DDL PARSER TABLE {record.name}: "
            f"{len(record.fields)} columns, PKS={primary_keys}"
        )

        for field_name, field in record.fields.items():
            print(
                f" COLUMN {field_name}: "
                f"{field.datatype} ({field.length}, {field.scale}) "
                f"NULLABLE={field.nullable}"
            )

    def _debug_unrecognized_datatype(
        self,
        table_name: str,
        column_name: str,
        datatype_text: str,
    ) -> None:
        if not self.DEBUG:
            return

        normalized = self._normalize_datatype_text(
            datatype_text,
        )

        print(
            "DDL PARSER SKIPPED COLUMN "
            f"{table_name}.{column_name}: "
            f"raw={repr(datatype_text)} "
            f"normalized={repr(normalized)} "
            f"leading={repr(self._leading_word(normalized))}"
        )