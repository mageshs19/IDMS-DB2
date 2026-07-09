from idms_db2_converter.generators.cobol_builder import Move
from idms_db2_converter.models import SchemaModel


class MetadataHelpers:
    def __init__(self, schema: SchemaModel):
        self.schema = schema

    def lookup_by_name(self, name: str) -> dict | None:
        for item in self.schema.output_semantics.get("lookups", []):
            if item.get("name", "").upper() == name.upper():
                return item

        return None

    def lookup_by_owner_set(self, owner_set: str) -> dict | None:
        for item in self.schema.output_semantics.get("lookups", []):
            if item.get("owner_set", "").upper() == owner_set.upper():
                return item

        return None

    def lookup_by_first_member_set(self, first_member_set: str) -> dict | None:
        for item in self.schema.output_semantics.get("lookups", []):
            if item.get("first_member_set", "").upper() == first_member_set.upper():
                return item

        return None

    def moves_to_nodes(self, moves: list[dict]) -> list[Move]:
        nodes = []

        for move in moves:
            source = self.map_source(move["from"])
            target = move["to"]
            nodes.append(Move(source=source, target=target))

        return nodes

    def map_source(self, source: str) -> str:
        source_upper = source.upper()

        if source_upper in self.schema.date_part_map:
            meta = self.schema.date_part_map[source_upper]
            return f"{meta['host']}({meta['substring_start']}:{meta['substring_length']})"

        if source_upper in self.schema.field_map:
            return self.schema.field_map[source_upper].get("host", source)

        return source