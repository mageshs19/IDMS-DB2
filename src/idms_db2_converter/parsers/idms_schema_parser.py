import re

from idms_db2_converter.generators.naming import Naming
from idms_db2_converter.models import Column, Record, Relationship, SchemaModel


class IdmsSchemaParser:
    RECORD_HEADER = re.compile(
        r"^RECORD NAME\.+\s+([A-Z0-9-]+)",
        re.IGNORECASE | re.MULTILINE,
    )

    LOCATION_CALC = re.compile(
        r"LOCATION MODE\.+\s+CALC USING\s+([A-Z0-9-]+)",
        re.IGNORECASE,
    )

    DBKEY_SET_ROLE = re.compile(
        r"^\s+([A-Z0-9-]+)\s+(?:INDEX\s+)?(OWNER|MEMBER)\b",
        re.IGNORECASE | re.MULTILINE,
    )

    DATA_LINE_PREFIX = re.compile(
        r"^\s*(0[2-5])\s+([A-Z0-9-]+)\s+(.*)$",
        re.IGNORECASE,
    )

    PICTURE_FIND = re.compile(
        r"S?9$\d+$V9$\d+$|"
        r"S?9$\d+$V9+|"
        r"S?9+V9$\d+$|"
        r"S?9+V9+|"
        r"S?V9$\d+$|"
        r"S?V9+|"
        r"S?9$\d+$|"
        r"S?9+|"
        r"X$\d+$|"
        r"X+",
        re.IGNORECASE,
    )

    DATE_PARTS = {
        "YEAR": {
            "substring_start": 1,
            "substring_length": 4,
        },
        "MONTH": {
            "substring_start": 5,
            "substring_length": 2,
        },
        "DAY": {
            "substring_start": 7,
            "substring_length": 2,
        },
    }

    def parse(self, text: str) -> SchemaModel:
        schema = SchemaModel()
        schema.schema_source = "IDMS_SCHEMA"

        blocks = self._record_blocks(text)
        set_roles: dict[str, dict[str, str]] = {}

        for record_name, block in blocks:
            self._parse_record(schema, record_name, block)
            self._collect_set_roles(set_roles, record_name, block)

        self._build_relationships(schema, set_roles)

        if hasattr(schema, "add_validation_message"):
            schema.add_validation_message("Schema built from IDMS schema listing.")

        return schema

    def _record_blocks(self, text: str) -> list[tuple[str, str]]:
        matches = list(self.RECORD_HEADER.finditer(text))
        result = []

        for index, match in enumerate(matches):
            record_name = match.group(1).upper()
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)

            result.append((record_name, text[start:end]))

        return result

    def _parse_record(
        self,
        schema: SchemaModel,
        record_name: str,
        block: str,
    ) -> None:
        primary_key = None

        calc_match = self.LOCATION_CALC.search(block)

        if calc_match:
            primary_key = self._normalize_column(calc_match.group(1))

        record = Record(
            name=record_name,
            primary_key=primary_key,
            fields={},
        )

        schema.record_table_map[record_name] = self._normalize_table(record_name)

        active_date_groups: dict[int, dict[str, str]] = {}

        for line in block.splitlines():
            parsed = self._parse_data_item_line(line)

            if not parsed:
                continue

            level = parsed["level"]
            raw_field_name = parsed["field_name"]
            body = parsed["body"]
            storage_length = parsed["length"]

            self._close_inactive_date_groups(active_date_groups, level)

            if raw_field_name == "FILLER":
                continue

            usage = self._extract_usage(body)
            picture = self._extract_picture(body)
            column_name = self._normalize_column(raw_field_name)

            if self._is_date_group(raw_field_name, picture, storage_length):
                if column_name not in record.fields:
                    record.fields[column_name] = Column(
                        name=column_name,
                        datatype="CHAR",
                        length=8,
                        scale=None,
                        nullable=False,
                    )

                host = Naming.hv(record_name, column_name)
                self._add_field_map(schema, raw_field_name, host)

                active_date_groups[level] = {
                    "raw_field_name": raw_field_name,
                    "column_name": column_name,
                    "host": host,
                }

                continue

            date_group = self._nearest_date_group(active_date_groups)

            if date_group and self._is_date_part(raw_field_name):
                self._add_date_part_map(
                    schema=schema,
                    idms_field=raw_field_name,
                    host=date_group["host"],
                )
                continue

            if not picture:
                continue

            datatype, column_length, scale = self._map_picture(
                picture=picture,
                usage=usage,
                storage_length=storage_length,
            )

            if column_name not in record.fields:
                record.fields[column_name] = Column(
                    name=column_name,
                    datatype=datatype,
                    length=column_length,
                    scale=scale,
                    nullable=False,
                )

            self._add_field_map(
                schema=schema,
                idms_field=raw_field_name,
                host=Naming.hv(record_name, column_name),
            )

        if primary_key and primary_key not in record.fields:
            record.fields[primary_key] = Column(
                name=primary_key,
                datatype="CHAR",
                length=12,
                scale=None,
                nullable=False,
            )

        schema.records[record_name] = record

    def _parse_data_item_line(self, line: str) -> dict | None:
        match = self.DATA_LINE_PREFIX.match(line)

        if not match:
            return None

        level = int(match.group(1))
        field_name = match.group(2).upper()
        remainder = match.group(3).strip()

        if field_name == "FILLER":
            return None

        parts = remainder.split()

        if len(parts) < 2:
            return None

        if not parts[-1].isdigit() or not parts[-2].isdigit():
            return None

        length = int(parts[-1])
        start = int(parts[-2])
        body = " ".join(parts[:-2])

        return {
            "level": level,
            "field_name": field_name,
            "body": body,
            "start": start,
            "length": length,
        }

    def _collect_set_roles(
        self,
        set_roles: dict[str, dict[str, str]],
        record_name: str,
        block: str,
    ) -> None:
        for match in self.DBKEY_SET_ROLE.finditer(block):
            set_name = match.group(1).upper()
            role = match.group(2).upper()

            if set_name == "CALC":
                continue

            set_roles.setdefault(set_name, {})

            if role == "OWNER":
                set_roles[set_name]["owner"] = record_name

            if role == "MEMBER":
                set_roles[set_name]["member"] = record_name

    def _build_relationships(
        self,
        schema: SchemaModel,
        set_roles: dict[str, dict[str, str]],
    ) -> None:
        for set_name, roles in set_roles.items():
            owner = roles.get("owner")
            member = roles.get("member")

            if not owner or not member:
                continue

            if owner not in schema.records or member not in schema.records:
                continue

            owner_record = schema.records[owner]
            member_record = schema.records[member]

            parent_key = owner_record.primary_key

            if not parent_key:
                continue

            child_fk = parent_key

            if child_fk not in member_record.fields:
                parent_column = owner_record.fields.get(parent_key)

                member_record.fields[child_fk] = Column(
                    name=child_fk,
                    datatype=parent_column.datatype if parent_column else "CHAR",
                    length=parent_column.length if parent_column else 12,
                    scale=parent_column.scale if parent_column else None,
                    nullable=True,
                )

            schema.relationships[set_name] = Relationship(
                set_name=set_name,
                parent_record=owner,
                child_record=member,
                cardinality="1:N",
                parent_key=parent_key,
                child_fk=child_fk,
                order_by=[child_fk],
            )

    def _extract_usage(self, body: str) -> str:
        upper = body.upper()

        if "COMP-3" in upper:
            return "COMP-3"

        if re.search(r"\bCOMP\b", upper):
            return "COMP"

        return "DISPLAY"

    def _extract_picture(self, body: str) -> str | None:
        upper = body.upper()
        matches = list(self.PICTURE_FIND.finditer(upper))

        if not matches:
            return None

        valid_matches = []

        for match in matches:
            value = match.group(0).upper()
            start = match.start()
            end = match.end()

            before = upper[start - 1] if start > 0 else " "
            after = upper[end] if end < len(upper) else " "

            if before.isalnum() or before in {"-", "_"}:
                continue

            if after.isalnum() or after in {"-", "_"}:
                continue

            valid_matches.append(value)

        if not valid_matches:
            return None

        return valid_matches[-1]

    def _map_picture(
        self,
        picture: str,
        usage: str,
        storage_length: int,
    ) -> tuple[str, int | None, int | None]:
        picture = picture.upper()
        usage = usage.upper()

        if picture.startswith("X"):
            length_match = re.search(r"X$(\d+)$", picture)

            if length_match:
                return "CHAR", int(length_match.group(1)), None

            return "CHAR", len(picture), None

        if "9" in picture:
            precision = self._numeric_precision(picture)
            scale = self._numeric_scale(picture)

            if usage == "DISPLAY":
                return "CHAR", storage_length, None

            if usage == "COMP":
                return "INTEGER", None, None

            return "DECIMAL", precision, scale

        return "CHAR", storage_length, None

    def _numeric_precision(self, picture: str) -> int:
        picture = picture.upper().replace("S", "")

        if "V" in picture:
            before_v, after_v = picture.split("V", 1)
        else:
            before_v = picture
            after_v = ""

        return self._count_9_digits(before_v) + self._count_9_digits(after_v)

    def _numeric_scale(self, picture: str) -> int:
        picture = picture.upper().replace("S", "")

        if "V" not in picture:
            return 0

        after_v = picture.split("V", 1)[1]

        return self._count_9_digits(after_v)

    def _count_9_digits(self, value: str) -> int:
        total = 0

        for match in re.finditer(r"9$(\d+)$|9", value):
            if match.group(1):
                total += int(match.group(1))
            else:
                total += 1

        return total

    def _is_date_group(
        self,
        raw_field_name: str,
        picture: str | None,
        storage_length: int,
    ) -> bool:
        normalized = self._normalize_column(raw_field_name)

        return (
            picture is None
            and normalized.endswith("DATE")
            and storage_length == 8
        )

    def _is_date_part(self, raw_field_name: str) -> bool:
        normalized = self._normalize_column(raw_field_name)

        return (
            normalized.endswith("_YEAR")
            or normalized.endswith("_MONTH")
            or normalized.endswith("_DAY")
        )

    def _add_date_part_map(
        self,
        schema: SchemaModel,
        idms_field: str,
        host: str,
    ) -> None:
        normalized = self._normalize_column(idms_field)

        if normalized.endswith("_YEAR"):
            part = "YEAR"
        elif normalized.endswith("_MONTH"):
            part = "MONTH"
        elif normalized.endswith("_DAY"):
            part = "DAY"
        else:
            return

        schema.date_part_map[idms_field.upper()] = {
            "host": host,
            "substring_start": self.DATE_PARTS[part]["substring_start"],
            "substring_length": self.DATE_PARTS[part]["substring_length"],
        }

    def _add_field_map(
        self,
        schema: SchemaModel,
        idms_field: str,
        host: str,
    ) -> None:
        schema.field_map[idms_field.upper()] = {
            "host": host,
        }

    def _close_inactive_date_groups(
        self,
        active_date_groups: dict[int, dict[str, str]],
        current_level: int,
    ) -> None:
        closed_levels = [
            level
            for level in active_date_groups
            if level >= current_level
        ]

        for level in closed_levels:
            del active_date_groups[level]

    def _nearest_date_group(
        self,
        active_date_groups: dict[int, dict[str, str]],
    ) -> dict[str, str] | None:
        if not active_date_groups:
            return None

        nearest_level = max(active_date_groups.keys())

        return active_date_groups[nearest_level]

    def _normalize_table(self, record_name: str) -> str:
        return record_name.upper().replace("-", "_")

    def _normalize_column(self, field_name: str) -> str:
        value = field_name.upper()
        value = re.sub(r"-\d{4}$", "", value)

        return value.replace("-", "_")