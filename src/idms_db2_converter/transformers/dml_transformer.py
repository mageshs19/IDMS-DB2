import re

from idms_db2_converter.exceptions import ConversionError
from idms_db2_converter.generators.naming import Naming
from idms_db2_converter.models import CobolAnalysis, SchemaModel


class DmlTransformer:
    """
    Converts IDMS update DML to DB2 embedded SQL.

    Supported mappings:
    - STORE record -> INSERT
    - MODIFY record -> UPDATE
    - ERASE record -> DELETE
    - READY AREA ... USAGE-MODE IS UPDATE -> CONTINUE
    - FINISH -> COMMIT for update programs

    Composite-key support:
    - UPDATE WHERE uses all effective primary keys.
    - DELETE WHERE uses all effective primary keys.
    - UPDATE excludes all primary key columns from SET list.
    - Single primary key remains fully supported.
    """

    STORE_RECORD = re.compile(
        r"^\s*STORE\s+([A-Z0-9-]+)\.?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    MODIFY_RECORD = re.compile(
        r"^\s*MODIFY\s+([A-Z0-9-]+)\.?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    ERASE_RECORD = re.compile(
        r"^\s*ERASE\s+([A-Z0-9-]+)\.?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    READY_UPDATE_BLOCK = re.compile(
        r"""
        ^\s*READY\s+AREA\s+[A-Z0-9-]+\.?\s*$
        (?:\n\s*USAGE-MODE\s+IS\s+UPDATE\.?\s*$)?
        (?:\n\s*PERFORM\s+IDMS-STATUS\.?\s*$)?
        """,
        re.IGNORECASE | re.MULTILINE | re.VERBOSE,
    )

    READY_AREA_LINE = re.compile(
        r"^\s*READY\s+AREA\s+[A-Z0-9-]+\.?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    USAGE_MODE_UPDATE_LINE = re.compile(
        r"^\s*USAGE-MODE\s+IS\s+UPDATE\.?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    FINISH_LINE = re.compile(
        r"^\s*FINISH\.?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    IDMS_STATUS_PERFORM = re.compile(
        r"^\s*PERFORM\s+IDMS-STATUS\.?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    DB2_CHECK_STATUS_PERFORM = re.compile(
        r"^\s*PERFORM\s+DB2-CHECK-STATUS\.?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    PARAGRAPH_HEADER = re.compile(
        r"^\s*([A-Z0-9-]+)\.\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    MOVE_TO_TARGET = re.compile(
        r"^\s*MOVE\s+.+?\s+TO\s+([A-Z0-9-]+)\.?\s*$",
        re.IGNORECASE,
    )

    def __init__(
        self,
        schema: SchemaModel,
        analysis: CobolAnalysis,
    ) -> None:
        self.schema = schema
        self.analysis = analysis

    def has_update_dml(
        self,
    ) -> bool:
        return bool(
            getattr(self.analysis, "store_records", [])
            or getattr(self.analysis, "modify_records", [])
            or getattr(self.analysis, "erase_records", [])
            or getattr(self.analysis, "ready_update_areas", [])
        )

    def transform(
        self,
        text: str,
    ) -> str:
        text = self.replace_ready_update_blocks(
            text,
        )

        text = self.replace_store(
            text,
        )

        text = self.replace_modify(
            text,
        )

        text = self.replace_erase(
            text,
        )

        text = self.replace_finish_with_commit(
            text,
        )

        text = self.remove_idms_status_performs(
            text,
        )

        text = self.insert_db2_check_status_paragraph(
            text,
        )

        return text

    def replace_ready_update_blocks(
        self,
        text: str,
    ) -> str:
        text = self.READY_UPDATE_BLOCK.sub(
            "       CONTINUE.",
            text,
        )

        text = self.READY_AREA_LINE.sub(
            "       CONTINUE.",
            text,
        )

        text = self.USAGE_MODE_UPDATE_LINE.sub(
            "",
            text,
        )

        return text

    def replace_store(
        self,
        text: str,
    ) -> str:
        def replacement(match: re.Match) -> str:
            record_name = match.group(1).upper()

            return self.insert_sql(
                record_name,
            )

        return self.STORE_RECORD.sub(
            replacement,
            text,
        )

    def replace_modify(
        self,
        text: str,
    ) -> str:
        matches = list(
            self.MODIFY_RECORD.finditer(text),
        )

        if not matches:
            return text

        pieces: list[str] = []
        last_position = 0

        for match in matches:
            record_name = match.group(1).upper()

            pieces.append(
                text[last_position : match.start()],
            )

            changed_columns = self.changed_columns_before_modify(
                text=text,
                modify_position=match.start(),
                logical_record_name=record_name,
            )

            pieces.append(
                self.update_sql(
                    logical_record_name=record_name,
                    changed_columns=changed_columns,
                )
            )

            last_position = match.end()

        pieces.append(
            text[last_position:],
        )

        return "".join(pieces)

    def replace_erase(
        self,
        text: str,
    ) -> str:
        def replacement(match: re.Match) -> str:
            record_name = match.group(1).upper()

            return self.delete_sql(
                record_name,
            )

        return self.ERASE_RECORD.sub(
            replacement,
            text,
        )

    def replace_finish_with_commit(
        self,
        text: str,
    ) -> str:
        return self.FINISH_LINE.sub(
            self.commit_sql(),
            text,
        )

    def remove_idms_status_performs(
        self,
        text: str,
    ) -> str:
        return self.IDMS_STATUS_PERFORM.sub(
            "",
            text,
        )

    def insert_sql(
        self,
        logical_record_name: str,
    ) -> str:
        physical_record_name = self.physical_record_name(
            logical_record_name,
        )

        record = self.schema.records.get(
            physical_record_name,
        )

        if not record:
            raise ConversionError(
                f"STORE references missing record {logical_record_name}."
            )

        columns = list(record.fields.keys())

        value_items = [
            self.host_with_indicator(
                logical_record_name=logical_record_name,
                column_name=column_name,
                nullable=record.fields[column_name].nullable,
            )
            for column_name in columns
        ]

        lines: list[str] = [
            "       EXEC SQL",
            f"            INSERT INTO {physical_record_name}",
            "            (",
        ]

        lines.extend(
            self.sql_list_lines(
                items=columns,
                indent="                ",
            )
        )

        lines.extend(
            [
                "            )",
                "            VALUES",
                "            (",
            ]
        )

        lines.extend(
            self.sql_list_lines(
                items=value_items,
                indent="                ",
            )
        )

        lines.extend(
            [
                "            )",
                "       END-EXEC.",
                "       PERFORM DB2-CHECK-STATUS.",
            ]
        )

        return "\n".join(lines)

    def update_sql(
        self,
        logical_record_name: str,
        changed_columns: list[str],
    ) -> str:
        physical_record_name = self.physical_record_name(
            logical_record_name,
        )

        record = self.schema.records.get(
            physical_record_name,
        )

        if not record:
            raise ConversionError(
                f"MODIFY references missing record {logical_record_name}."
            )

        primary_keys = self.resolve_primary_keys(
            logical_record_name=logical_record_name,
            physical_record_name=physical_record_name,
        )

        if not primary_keys:
            raise ConversionError(
                f"MODIFY record {logical_record_name} has no primary key."
            )

        primary_key_set = set(primary_keys)

        update_columns = [
            column_name
            for column_name in changed_columns
            if column_name in record.fields
            and column_name not in primary_key_set
        ]

        if not update_columns:
            update_columns = [
                column_name
                for column_name in record.fields.keys()
                if column_name not in primary_key_set
            ]

        if not update_columns:
            raise ConversionError(
                f"MODIFY record {logical_record_name} has no update columns."
            )

        set_items = []

        for column_name in update_columns:
            column = record.fields[column_name]

            host = self.host_with_indicator(
                logical_record_name=logical_record_name,
                column_name=column_name,
                nullable=column.nullable,
            )

            set_items.append(
                f"{column_name} = {host}"
            )

        where_items = self.where_items_for_primary_keys(
            logical_record_name=logical_record_name,
            primary_keys=primary_keys,
        )

        lines: list[str] = [
            "       EXEC SQL",
            f"            UPDATE {physical_record_name}",
        ]

        lines.extend(
            self.sql_assignment_lines(
                keyword="SET",
                items=set_items,
                indent="            ",
            )
        )

        lines.extend(
            self.where_lines(
                where_items=where_items,
                indent="            ",
            )
        )

        lines.extend(
            [
                "       END-EXEC.",
                "       PERFORM DB2-CHECK-STATUS.",
            ]
        )

        return "\n".join(lines)

    def delete_sql(
        self,
        logical_record_name: str,
    ) -> str:
        physical_record_name = self.physical_record_name(
            logical_record_name,
        )

        record = self.schema.records.get(
            physical_record_name,
        )

        if not record:
            raise ConversionError(
                f"ERASE references missing record {logical_record_name}."
            )

        primary_keys = self.resolve_primary_keys(
            logical_record_name=logical_record_name,
            physical_record_name=physical_record_name,
        )

        if not primary_keys:
            raise ConversionError(
                f"ERASE record {logical_record_name} has no primary key."
            )

        where_items = self.where_items_for_primary_keys(
            logical_record_name=logical_record_name,
            primary_keys=primary_keys,
        )

        lines = [
            "       EXEC SQL",
            f"            DELETE FROM {physical_record_name}",
        ]

        lines.extend(
            self.where_lines(
                where_items=where_items,
                indent="            ",
            )
        )

        lines.extend(
            [
                "       END-EXEC.",
                "       PERFORM DB2-CHECK-STATUS.",
            ]
        )

        return "\n".join(lines)

    def commit_sql(
        self,
    ) -> str:
        return "\n".join(
            [
                "       EXEC SQL",
                "            COMMIT",
                "       END-EXEC.",
                "       PERFORM DB2-CHECK-STATUS.",
            ]
        )

    def insert_db2_check_status_paragraph(
        self,
        text: str,
    ) -> str:
        if re.search(
            r"^\s*DB2-CHECK-STATUS\.\s*$",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        ):
            return text

        paragraph = "\n".join(
            [
                "",
                "DB2-CHECK-STATUS.",
                "       IF SQLCODE NOT = 0",
                "          DISPLAY 'DB2 SQL ERROR SQLCODE=' SQLCODE",
                "       END-IF.",
            ]
        )

        if re.search(
            r"\n\s*MAIN-LINE\.",
            text,
            flags=re.IGNORECASE,
        ):
            return re.sub(
                r"(?=\n\s*MAIN-LINE\.)",
                paragraph,
                text,
                count=1,
                flags=re.IGNORECASE,
            )

        return text.rstrip() + paragraph

    def changed_columns_before_modify(
        self,
        text: str,
        modify_position: int,
        logical_record_name: str,
    ) -> list[str]:
        paragraph_text = self.current_paragraph_text(
            text=text,
            position=modify_position,
        )

        physical_record_name = self.physical_record_name(
            logical_record_name,
        )

        record = self.schema.records.get(
            physical_record_name,
        )

        if not record:
            return []

        changed_columns: list[str] = []
        seen: set[str] = set()

        for line in paragraph_text.splitlines():
            match = self.MOVE_TO_TARGET.match(
                line,
            )

            if not match:
                continue

            target = match.group(1).upper()

            column_name = self.column_from_move_target(
                logical_record_name=logical_record_name,
                physical_record_name=physical_record_name,
                target=target,
            )

            if not column_name:
                continue

            if column_name not in record.fields:
                continue

            if column_name in seen:
                continue

            seen.add(
                column_name,
            )

            changed_columns.append(
                column_name,
            )

        return changed_columns

    def current_paragraph_text(
        self,
        text: str,
        position: int,
    ) -> str:
        paragraph_start = 0

        for match in self.PARAGRAPH_HEADER.finditer(
            text,
            0,
            position,
        ):
            paragraph_start = match.start()

        return text[paragraph_start:position]

    def column_from_move_target(
        self,
        logical_record_name: str,
        physical_record_name: str,
        target: str,
    ) -> str | None:
        record = self.schema.records.get(
            physical_record_name,
        )

        if not record:
            return None

        target = target.upper().rstrip(".")
        target_as_column = self.normalize_column_token(
            target,
        )

        direct = self.find_matching_column(
            record_fields=list(record.fields.keys()),
            candidate=target_as_column,
        )

        if direct:
            return direct

        field_map_result = self.column_from_field_map(
            logical_record_name=logical_record_name,
            target=target,
            record_fields=list(record.fields.keys()),
        )

        if field_map_result:
            return field_map_result

        host_result = self.column_from_host_variable(
            logical_record_name=logical_record_name,
            target=target,
            record_fields=list(record.fields.keys()),
        )

        if host_result:
            return host_result

        return None

    def column_from_field_map(
        self,
        logical_record_name: str,
        target: str,
        record_fields: list[str],
    ) -> str | None:
        field_map = getattr(
            self.schema,
            "field_map",
            {},
        )

        meta = field_map.get(
            target.upper(),
        )

        if not meta:
            meta = field_map.get(
                target.upper().replace("-", "_"),
            )

        if not isinstance(meta, dict):
            return None

        column = meta.get(
            "column",
        )

        if column:
            matched = self.find_matching_column(
                record_fields=record_fields,
                candidate=self.normalize_column_token(str(column)),
            )

            if matched:
                return matched

        host = meta.get(
            "host",
        )

        if host:
            return self.column_from_host_variable(
                logical_record_name=logical_record_name,
                target=str(host).upper(),
                record_fields=record_fields,
            )

        return None

    def column_from_host_variable(
        self,
        logical_record_name: str,
        target: str,
        record_fields: list[str],
    ) -> str | None:
        normalized_target = target.upper().replace("_", "-")
        normalized_record = logical_record_name.upper().replace("_", "-")
        prefix = f"HV-{normalized_record}-"

        if not normalized_target.startswith(prefix):
            return None

        column_part = normalized_target[len(prefix) :]
        candidate = self.normalize_column_token(
            column_part,
        )

        return self.find_matching_column(
            record_fields=record_fields,
            candidate=candidate,
        )

    def find_matching_column(
        self,
        record_fields: list[str],
        candidate: str,
    ) -> str | None:
        candidate = candidate.upper()

        for field_name in record_fields:
            if field_name.upper() == candidate:
                return field_name

        candidate_hyphen = candidate.replace("_", "-")

        for field_name in record_fields:
            if field_name.upper().replace("_", "-") == candidate_hyphen:
                return field_name

        candidate_compact = self.compact_name(
            candidate,
        )

        for field_name in record_fields:
            field_compact = self.compact_name(
                field_name,
            )

            if field_compact == candidate_compact:
                return field_name

        return None

    def resolve_primary_keys(
        self,
        logical_record_name: str,
        physical_record_name: str,
    ) -> list[str]:
        record = self.schema.records.get(
            physical_record_name,
        )

        if not record:
            return []

        record_fields = list(
            record.fields.keys(),
        )

        calc_keys = self.primary_keys_from_calc_key_map(
            logical_record_name=logical_record_name,
            physical_record_name=physical_record_name,
            record_fields=record_fields,
        )

        if calc_keys:
            return calc_keys

        if hasattr(record, "effective_primary_keys"):
            effective = record.effective_primary_keys()
        else:
            effective = list(getattr(record, "primary_keys", []) or [])

            if getattr(record, "primary_key", None):
                if record.primary_key not in effective:
                    effective.append(record.primary_key)

        matched_effective = []

        for key in effective:
            matched = self.find_matching_column(
                record_fields=record_fields,
                candidate=self.normalize_column_token(key),
            )

            if matched:
                matched_effective.append(
                    matched,
                )

        if matched_effective:
            return matched_effective

        preferred_id = self.preferred_id_column(
            logical_record_name=logical_record_name,
            record_fields=record_fields,
        )

        if preferred_id:
            return [preferred_id]

        if record_fields:
            return [record_fields[0]]

        return []

    def primary_keys_from_calc_key_map(
        self,
        logical_record_name: str,
        physical_record_name: str,
        record_fields: list[str],
    ) -> list[str]:
        calc_key_map = getattr(
            self.schema,
            "calc_key_map",
            {},
        )

        possible_keys = [
            logical_record_name.upper(),
            logical_record_name.upper().replace("-", "_"),
            physical_record_name.upper(),
            physical_record_name.upper().replace("-", "_"),
        ]

        for key in possible_keys:
            meta = calc_key_map.get(
                key,
            )

            if not isinstance(meta, dict):
                continue

            raw_keys = []

            if meta.get("primary_keys"):
                raw_keys.extend(
                    meta.get("primary_keys") or [],
                )

            for single_key_name in [
                "key",
                "primary_key",
                "column",
            ]:
                value = meta.get(
                    single_key_name,
                )

                if value:
                    raw_keys.append(
                        value,
                    )

            result = []
            seen = set()

            for raw_key in raw_keys:
                matched = self.find_matching_column(
                    record_fields=record_fields,
                    candidate=self.normalize_column_token(str(raw_key)),
                )

                if not matched:
                    continue

                if matched in seen:
                    continue

                seen.add(
                    matched,
                )

                result.append(
                    matched,
                )

            if result:
                return result

        return []

    def preferred_id_column(
        self,
        logical_record_name: str,
        record_fields: list[str],
    ) -> str | None:
        id_columns = [
            field_name
            for field_name in record_fields
            if re.search(
                r"(^|_)ID(_|$)",
                field_name.upper(),
            )
        ]

        if not id_columns:
            return None

        logical_prefix = logical_record_name.upper().replace("-", "_").split("_")[0]

        for field_name in id_columns:
            first_token = field_name.upper().split("_")[0]

            if first_token.startswith(
                logical_prefix[:3],
            ):
                return field_name

        return id_columns[0]

    def where_items_for_primary_keys(
        self,
        logical_record_name: str,
        primary_keys: list[str],
    ) -> list[str]:
        return [
            f"{primary_key} = :{Naming.hv(logical_record_name, primary_key)}"
            for primary_key in primary_keys
        ]

    def where_lines(
        self,
        where_items: list[str],
        indent: str,
    ) -> list[str]:
        lines = []

        for index, item in enumerate(where_items):
            if index == 0:
                lines.append(
                    f"{indent}WHERE {item}"
                )
            else:
                lines.append(
                    f"{indent}  AND {item}"
                )

        return lines

    def sql_assignment_lines(
        self,
        keyword: str,
        items: list[str],
        indent: str,
    ) -> list[str]:
        lines = []

        for index, item in enumerate(items):
            suffix = "," if index < len(items) - 1 else ""

            if index == 0:
                lines.append(
                    f"{indent}{keyword} {item}{suffix}"
                )
            else:
                lines.append(
                    f"{indent}    {item}{suffix}"
                )

        return lines

    def sql_list_lines(
        self,
        items: list[str],
        indent: str,
    ) -> list[str]:
        lines = []

        for index, item in enumerate(items):
            suffix = "," if index < len(items) - 1 else ""

            lines.append(
                f"{indent}{item}{suffix}"
            )

        return lines

    def physical_record_name(
        self,
        logical_record_name: str,
    ) -> str:
        logical_record_name = logical_record_name.upper()

        mapped = self.schema.record_table_map.get(
            logical_record_name,
        )

        if mapped and mapped in self.schema.records:
            return mapped

        normalized = logical_record_name.replace(
            "-",
            "_",
        )

        mapped = self.schema.record_table_map.get(
            normalized,
        )

        if mapped and mapped in self.schema.records:
            return mapped

        if logical_record_name in self.schema.records:
            return logical_record_name

        if normalized in self.schema.records:
            return normalized

        return logical_record_name

    def host_with_indicator(
        self,
        logical_record_name: str,
        column_name: str,
        nullable: bool,
    ) -> str:
        host = f":{Naming.hv(logical_record_name, column_name)}"

        if nullable:
            host += f" :{Naming.ni(logical_record_name, column_name)}"

        return host

    def normalize_column_token(
        self,
        value: str,
    ) -> str:
        return (
            str(value or "")
            .upper()
            .strip()
            .rstrip(".")
            .replace("-", "_")
            .replace(" ", "_")
        )

    def compact_name(
        self,
        value: str,
    ) -> str:
        return re.sub(
            r"[^A-Z0-9]",
            "",
            str(value or "").upper(),
        )