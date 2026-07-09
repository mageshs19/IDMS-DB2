from idms_db2_converter.generators.naming import Naming
from idms_db2_converter.models import SchemaModel


class FetchParagraphGenerator:
    """
    Generates complete FETCH paragraphs for cursor-based IDMS set walking.

    Guarantees:
    - FETCH statement has END-EXEC.
    - SQLCODE handling is emitted after FETCH.
    - INTO list matches every selected column in the cursor.
    """

    def __init__(
        self,
        schema: SchemaModel
    ):
        self.schema = schema

    def paragraph_name(
        self,
        set_name: str
    ) -> str:

        return f"FETCH-{set_name}".upper()

    def generate(
        self,
        used_sets: list[str]
    ) -> str:

        print(
            "USING FETCH_PARAGRAPH_GENERATOR VERSION COMPLETE-SQLCODE-2026-07-01"
        )

        paragraphs: list[str] = []
        seen: set[str] = set()

        for set_name in used_sets:
            set_name = set_name.upper()

            if set_name in seen:
                continue

            seen.add(set_name)

            if set_name not in self.schema.relationships:
                continue

            paragraph = self._generate_one(
                set_name
            )

            if paragraph.strip():
                paragraphs.append(
                    paragraph
                )

        return "\n\n".join(
            paragraphs
        )

    def _generate_one(
        self,
        set_name: str
    ) -> str:

        relationship = self.schema.relationships[
            set_name
        ]

        child_record_name = self._physical_record_name(
            relationship.child_record
        )

        child_record = self.schema.records.get(
            child_record_name
        )

        if child_record is None:
            return ""

        into_items: list[str] = []

        for column_name, column in child_record.fields.items():
            host = (
                f":{Naming.hv(relationship.child_record, column_name)}"
            )

            if column.nullable:
                host += (
                    f" :{Naming.ni(relationship.child_record, column_name)}"
                )

            into_items.append(
                host
            )

        lines: list[str] = [
            f"{self.paragraph_name(set_name)}.",
            "       EXEC SQL",
            f"            FETCH {Naming.cursor(set_name)}"
        ]

        for index, item in enumerate(into_items):
            suffix = "," if index < len(into_items) - 1 else ""

            if index == 0:
                lines.append(
                    f"             INTO {item}{suffix}"
                )
            else:
                lines.append(
                    f"                  {item}{suffix}"
                )

        lines.extend(
            [
                "       END-EXEC.",
                "",
                "       IF SQLCODE NOT = 0 AND SQLCODE NOT = 100",
                "          PERFORM SQL-ERROR",
                "       END-IF."
            ]
        )

        return "\n".join(
            lines
        )

    def _physical_record_name(
        self,
        logical_record_name: str
    ) -> str:

        logical_record_name = logical_record_name.upper()

        mapped = self.schema.record_table_map.get(
            logical_record_name
        )

        if mapped and mapped in self.schema.records:
            return mapped

        normalized = logical_record_name.replace(
            "-",
            "_"
        )

        mapped = self.schema.record_table_map.get(
            normalized
        )

        if mapped and mapped in self.schema.records:
            return mapped

        if logical_record_name in self.schema.records:
            return logical_record_name

        if normalized in self.schema.records:
            return normalized

        return logical_record_name