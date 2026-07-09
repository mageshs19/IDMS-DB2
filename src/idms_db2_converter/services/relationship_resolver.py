import json

from idms_db2_converter.exceptions import ConversionError
from idms_db2_converter.models import CobolAnalysis, Relationship, SchemaModel


class RelationshipResolver:
    """
    Resolves COBOL IDMS set names to schema relationships.

    No business-specific set names are hard-coded.

    Resolution order:
    1. Use exact set name if already present.
    2. Use relationship overrides if provided.
    3. Use DDL-derived relationships if a COBOL set can be matched unambiguously.
    """

    def apply_overrides(
        self,
        schema: SchemaModel,
        relationship_overrides_json: str,
    ) -> SchemaModel:
        try:
            payload = json.loads(relationship_overrides_json)
        except json.JSONDecodeError as exc:
            raise ConversionError(f"Invalid relationship override JSON: {exc}") from exc

        self._apply_record_aliases(schema, payload)

        for item in payload.get("relationships", []):
            self._apply_relationship_override(schema, item)

        return schema

    def resolve_cobol_sets(
        self,
        schema: SchemaModel,
        analysis: CobolAnalysis,
    ) -> SchemaModel:
        references = self._collect_set_references(analysis)

        for set_name, child_records in references.items():
            if set_name in schema.relationships:
                continue

            matched = self._find_unambiguous_relationship(
                schema=schema,
                set_name=set_name,
                child_records=child_records,
            )

            if not matched:
                continue

            schema.relationships[set_name] = Relationship(
                set_name=set_name,
                parent_record=matched.parent_record,
                child_record=matched.child_record,
                cardinality=matched.cardinality,
                parent_key=matched.parent_key,
                child_fk=matched.child_fk,
                order_by=matched.order_by,
            )

            schema.add_validation_message(
                f"Set {set_name} resolved from existing schema relationship "
                f"{matched.parent_record}-{matched.child_record}."
            )

        return schema

    def _collect_set_references(
        self,
        analysis: CobolAnalysis,
    ) -> dict[str, set[str]]:
        references: dict[str, set[str]] = {}

        for record_name, set_name in analysis.obtain_next:
            references.setdefault(set_name, set()).add(record_name)

        for set_name in analysis.obtain_owner_sets:
            references.setdefault(set_name, set())

        for set_name in analysis.find_first_sets:
            references.setdefault(set_name, set())

        return references

    def _apply_record_aliases(self, schema: SchemaModel, payload: dict) -> None:
        for item in payload.get("record_aliases", []):
            record_name = item["record"].upper()
            table_name = item["table"].upper()

            if table_name not in schema.records:
                raise ConversionError(
                    f"Record alias {record_name} references unknown table {table_name}."
                )

            schema.records[record_name] = schema.records[table_name]
            schema.record_table_map[record_name] = table_name

    def _apply_relationship_override(self, schema: SchemaModel, item: dict) -> None:
        set_name = item["set_name"].upper()

        parent_record = self._upper_or_none(item.get("parent_record"))
        child_record = self._upper_or_none(item.get("child_record"))
        parent_key = self._upper_or_none(item.get("parent_key"))
        child_fk = self._upper_or_none(item.get("child_fk"))
        order_by = [value.upper() for value in item.get("order_by", [])]

        if set_name in schema.relationships:
            rel = schema.relationships[set_name]

            if parent_record:
                rel.parent_record = parent_record

            if child_record:
                rel.child_record = child_record

            if parent_key:
                rel.parent_key = parent_key

            if child_fk:
                rel.child_fk = child_fk

            if order_by:
                rel.order_by = order_by

            return

        if parent_record and child_record:
            self._create_explicit_relationship(
                schema=schema,
                set_name=set_name,
                parent_record=parent_record,
                child_record=child_record,
                parent_key=parent_key,
                child_fk=child_fk,
                order_by=order_by,
            )
            return

        matched = self._find_relationship_by_keys(
            schema=schema,
            parent_key=parent_key,
            child_fk=child_fk,
        )

        if matched:
            schema.relationships[set_name] = Relationship(
                set_name=set_name,
                parent_record=matched.parent_record,
                child_record=matched.child_record,
                cardinality=matched.cardinality,
                parent_key=parent_key or matched.parent_key,
                child_fk=child_fk or matched.child_fk,
                order_by=order_by or matched.order_by,
            )
            return

        raise ConversionError(
            f"Override references set {set_name}, but it could not be resolved. "
            "Provide parent_record and child_record, or provide keys matching a DDL foreign key."
        )

    def _create_explicit_relationship(
        self,
        schema: SchemaModel,
        set_name: str,
        parent_record: str,
        child_record: str,
        parent_key: str | None,
        child_fk: str | None,
        order_by: list[str],
    ) -> None:
        if parent_record not in schema.records:
            raise ConversionError(
                f"Set {set_name} parent_record {parent_record} is not present in schema."
            )

        if child_record not in schema.records:
            raise ConversionError(
                f"Set {set_name} child_record {child_record} is not present in schema."
            )

        parent = schema.records[parent_record]
        child = schema.records[child_record]

        resolved_parent_key = parent_key or parent.primary_key

        if not resolved_parent_key:
            raise ConversionError(
                f"Set {set_name} cannot resolve parent_key."
            )

        resolved_child_fk = child_fk

        if not resolved_child_fk and resolved_parent_key in child.fields:
            resolved_child_fk = resolved_parent_key

        if not resolved_child_fk:
            raise ConversionError(
                f"Set {set_name} cannot resolve child_fk."
            )

        schema.relationships[set_name] = Relationship(
            set_name=set_name,
            parent_record=parent_record,
            child_record=child_record,
            cardinality="1:N",
            parent_key=resolved_parent_key,
            child_fk=resolved_child_fk,
            order_by=order_by or [resolved_child_fk],
        )

    def _find_relationship_by_keys(
        self,
        schema: SchemaModel,
        parent_key: str | None,
        child_fk: str | None,
    ) -> Relationship | None:
        if not parent_key and not child_fk:
            return None

        matches = []

        for rel in schema.relationships.values():
            if parent_key and rel.parent_key != parent_key:
                continue

            if child_fk and rel.child_fk != child_fk:
                continue

            matches.append(rel)

        if len(matches) == 1:
            return matches[0]

        if len(matches) > 1:
            raise ConversionError(
                "Relationship override is ambiguous. Add parent_record and child_record."
            )

        return None

    def _find_unambiguous_relationship(
        self,
        schema: SchemaModel,
        set_name: str,
        child_records: set[str],
    ) -> Relationship | None:
        candidates = list(schema.relationships.values())

        if child_records:
            filtered = [
                rel
                for rel in candidates
                if rel.child_record in child_records
            ]

            if filtered:
                candidates = filtered

        if len(candidates) == 1:
            return candidates[0]

        scored = []

        for rel in candidates:
            score = self._score_relationship(set_name, rel)

            if score > 0:
                scored.append((score, rel))

        if not scored:
            return None

        scored.sort(key=lambda item: item[0], reverse=True)

        top_score = scored[0][0]
        top_matches = [
            rel
            for score, rel in scored
            if score == top_score
        ]

        if len(top_matches) == 1:
            return top_matches[0]

        return None

    def _score_relationship(self, set_name: str, rel: Relationship) -> int:
        tokens = [
            token
            for token in set_name.replace("_", "-").split("-")
            if token
        ]

        searchable_values = [
            rel.parent_record,
            rel.child_record,
            rel.parent_key or "",
            rel.child_fk or "",
        ]

        score = 0

        for token in tokens:
            for value in searchable_values:
                if self._token_matches(token, value):
                    score += 1

        return score

    def _token_matches(self, token: str, value: str) -> bool:
        token = token.upper()
        value = value.upper()

        return token in value or value in token

    def _upper_or_none(self, value: str | None) -> str | None:
        return value.upper() if value else None