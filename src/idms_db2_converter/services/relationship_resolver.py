import json

from idms_db2_converter.exceptions import ConversionError
from idms_db2_converter.models import CobolAnalysis, Relationship, SchemaModel


class RelationshipResolver:
    """
    Resolves COBOL IDMS set names to schema relationships.

    Composite-key support:
    - Supports parent_keys and child_fks in override JSON.
    - Supports parent_key and child_fk for backward compatibility.
    - Resolves existing relationships using effective_parent_keys/effective_child_fks.
    - Preserves parent_key/child_fk as first pair for older code.
    """

    def apply_overrides(
        self,
        schema: SchemaModel,
        relationship_overrides_json: str,
    ) -> SchemaModel:
        try:
            payload = json.loads(
                relationship_overrides_json,
            )
        except json.JSONDecodeError as exc:
            raise ConversionError(f"Invalid relationship override JSON: {exc}") from exc

        self._apply_record_aliases(
            schema=schema,
            payload=payload,
        )

        for item in payload.get("relationships", []) or []:
            if not isinstance(item, dict):
                continue

            self._apply_relationship_override(
                schema=schema,
                item=item,
            )

        return schema

    def resolve_cobol_sets(
        self,
        schema: SchemaModel,
        analysis: CobolAnalysis,
    ) -> SchemaModel:
        references = self._collect_set_references(
            analysis,
        )

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

            parent_keys = self._effective_parent_keys(
                matched,
            )

            child_fks = self._effective_child_fks(
                matched,
            )

            schema.relationships[set_name] = Relationship(
                set_name=set_name,
                parent_record=matched.parent_record,
                child_record=matched.child_record,
                cardinality=matched.cardinality,
                parent_key=parent_keys[0] if parent_keys else matched.parent_key,
                child_fk=child_fks[0] if child_fks else matched.child_fk,
                parent_keys=parent_keys,
                child_fks=child_fks,
                order_by=matched.order_by or child_fks,
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

        for record_name, set_name in getattr(analysis, "obtain_next", []) or []:
            references.setdefault(set_name, set()).add(record_name)

        for set_name in getattr(analysis, "obtain_owner_sets", []) or []:
            references.setdefault(set_name, set())

        for set_name in getattr(analysis, "find_first_sets", []) or []:
            references.setdefault(set_name, set())

        return references

    def _apply_record_aliases(
        self,
        schema: SchemaModel,
        payload: dict,
    ) -> None:
        for item in payload.get("record_aliases", []) or []:
            if not isinstance(item, dict):
                continue

            record_name = self._upper_or_none(item.get("record"))
            table_name = self._upper_or_none(item.get("table"))

            if not record_name or not table_name:
                continue

            if table_name not in schema.records:
                raise ConversionError(
                    f"Record alias {record_name} references unknown table {table_name}."
                )

            schema.records[record_name] = schema.records[table_name]
            schema.record_table_map[record_name] = table_name

    def _apply_relationship_override(
        self,
        schema: SchemaModel,
        item: dict,
    ) -> None:
        set_name = self._upper_or_none(
            item.get("set_name")
            or item.get("name")
            or item.get("relationship")
        )

        if not set_name:
            return

        parent_record = self._upper_or_none(
            item.get("parent_record")
            or item.get("owner_record")
            or item.get("parent_table")
        )

        child_record = self._upper_or_none(
            item.get("child_record")
            or item.get("member_record")
            or item.get("child_table")
        )

        parent_keys = self._extract_key_list(
            source=item,
            plural_keys=[
                "parent_keys",
                "owner_keys",
            ],
            single_keys=[
                "parent_key",
                "owner_key",
                "parent_pk",
            ],
        )

        child_fks = self._extract_key_list(
            source=item,
            plural_keys=[
                "child_fks",
                "member_fks",
                "foreign_keys",
            ],
            single_keys=[
                "child_fk",
                "member_fk",
                "foreign_key",
                "child_pk",
            ],
        )

        order_by = [
            self._normalize_name(value)
            for value in item.get("order_by", []) or []
            if self._normalize_name(value)
        ]

        if set_name in schema.relationships:
            rel = schema.relationships[set_name]

            if parent_record:
                rel.parent_record = parent_record

            if child_record:
                rel.child_record = child_record

            if parent_keys:
                rel.parent_keys = parent_keys
                rel.parent_key = parent_keys[0]

            if child_fks:
                rel.child_fks = child_fks
                rel.child_fk = child_fks[0]

            if order_by:
                rel.order_by = order_by

            self._validate_relationship_keys(
                schema=schema,
                relationship=rel,
                set_name=set_name,
            )

            return

        if parent_record and child_record:
            self._create_explicit_relationship(
                schema=schema,
                set_name=set_name,
                parent_record=parent_record,
                child_record=child_record,
                parent_keys=parent_keys,
                child_fks=child_fks,
                order_by=order_by,
            )
            return

        matched = self._find_relationship_by_keys(
            schema=schema,
            parent_keys=parent_keys,
            child_fks=child_fks,
        )

        if matched:
            matched_parent_keys = parent_keys or self._effective_parent_keys(matched)
            matched_child_fks = child_fks or self._effective_child_fks(matched)

            schema.relationships[set_name] = Relationship(
                set_name=set_name,
                parent_record=matched.parent_record,
                child_record=matched.child_record,
                cardinality=matched.cardinality,
                parent_key=matched_parent_keys[0] if matched_parent_keys else matched.parent_key,
                child_fk=matched_child_fks[0] if matched_child_fks else matched.child_fk,
                parent_keys=matched_parent_keys,
                child_fks=matched_child_fks,
                order_by=order_by or matched.order_by or matched_child_fks,
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
        parent_keys: list[str],
        child_fks: list[str],
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

        resolved_parent_keys = parent_keys or self._effective_primary_keys(parent)

        if not resolved_parent_keys:
            raise ConversionError(
                f"Set {set_name} cannot resolve parent_keys."
            )

        resolved_child_fks = child_fks or self._resolve_child_fks(
            parent_keys=resolved_parent_keys,
            child=child,
        )

        if not resolved_child_fks:
            raise ConversionError(
                f"Set {set_name} cannot resolve child_fks."
            )

        if len(resolved_parent_keys) != len(resolved_child_fks):
            raise ConversionError(
                f"Set {set_name} has mismatched composite key counts: "
                f"{len(resolved_parent_keys)} parent key(s), "
                f"{len(resolved_child_fks)} child FK(s)."
            )

        for parent_key in resolved_parent_keys:
            if parent_key not in parent.fields:
                raise ConversionError(
                    f"Set {set_name} parent key {parent_key} is not present in {parent_record}."
                )

        for child_fk in resolved_child_fks:
            if child_fk not in child.fields:
                raise ConversionError(
                    f"Set {set_name} child FK {child_fk} is not present in {child_record}."
                )

        schema.relationships[set_name] = Relationship(
            set_name=set_name,
            parent_record=parent_record,
            child_record=child_record,
            cardinality="1:N",
            parent_key=resolved_parent_keys[0],
            child_fk=resolved_child_fks[0],
            parent_keys=resolved_parent_keys,
            child_fks=resolved_child_fks,
            order_by=order_by or resolved_child_fks.copy(),
        )

    def _find_relationship_by_keys(
        self,
        schema: SchemaModel,
        parent_keys: list[str],
        child_fks: list[str],
    ) -> Relationship | None:
        if not parent_keys and not child_fks:
            return None

        matches = []

        for rel in schema.relationships.values():
            rel_parent_keys = self._effective_parent_keys(rel)
            rel_child_fks = self._effective_child_fks(rel)

            if parent_keys and rel_parent_keys != parent_keys:
                continue

            if child_fks and rel_child_fks != child_fks:
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
            score = self._score_relationship(
                set_name=set_name,
                rel=rel,
            )

            if score > 0:
                scored.append(
                    (
                        score,
                        rel,
                    )
                )

        if not scored:
            return None

        scored.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        top_score = scored[0][0]

        top_matches = [
            rel
            for score, rel in scored
            if score == top_score
        ]

        if len(top_matches) == 1:
            return top_matches[0]

        return None

    def _score_relationship(
        self,
        set_name: str,
        rel: Relationship,
    ) -> int:
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

        searchable_values.extend(
            self._effective_parent_keys(rel)
        )

        searchable_values.extend(
            self._effective_child_fks(rel)
        )

        score = 0

        for token in tokens:
            for value in searchable_values:
                if self._token_matches(token, value):
                    score += 1

        return score

    def _validate_relationship_keys(
        self,
        schema: SchemaModel,
        relationship: Relationship,
        set_name: str,
    ) -> None:
        if relationship.parent_record not in schema.records:
            raise ConversionError(
                f"Set {set_name} parent_record {relationship.parent_record} is not present in schema."
            )

        if relationship.child_record not in schema.records:
            raise ConversionError(
                f"Set {set_name} child_record {relationship.child_record} is not present in schema."
            )

        parent = schema.records[relationship.parent_record]
        child = schema.records[relationship.child_record]

        parent_keys = self._effective_parent_keys(relationship)
        child_fks = self._effective_child_fks(relationship)

        if not parent_keys:
            parent_keys = self._effective_primary_keys(parent)
            relationship.parent_keys = parent_keys
            relationship.parent_key = parent_keys[0] if parent_keys else None

        if not child_fks:
            child_fks = self._resolve_child_fks(
                parent_keys=parent_keys,
                child=child,
            )
            relationship.child_fks = child_fks
            relationship.child_fk = child_fks[0] if child_fks else None

        if len(parent_keys) != len(child_fks):
            raise ConversionError(
                f"Set {set_name} has mismatched composite key counts: "
                f"{len(parent_keys)} parent key(s), {len(child_fks)} child FK(s)."
            )

        for parent_key in parent_keys:
            if parent_key not in parent.fields:
                raise ConversionError(
                    f"Set {set_name} parent key {parent_key} is not present in {relationship.parent_record}."
                )

        for child_fk in child_fks:
            if child_fk not in child.fields:
                raise ConversionError(
                    f"Set {set_name} child FK {child_fk} is not present in {relationship.child_record}."
                )

        if not relationship.order_by:
            relationship.order_by = child_fks.copy()

    def _resolve_child_fks(
        self,
        parent_keys: list[str],
        child,
    ) -> list[str]:
        child_fks = []

        for parent_key in parent_keys:
            if parent_key in child.fields:
                child_fks.append(parent_key)
                continue

            parent_base = self._remove_record_suffix(parent_key)

            matched = None

            for child_field_name in child.fields:
                child_base = self._remove_record_suffix(child_field_name)

                if child_base == parent_base:
                    matched = child_field_name
                    break

            if matched:
                child_fks.append(matched)

        if len(child_fks) == len(parent_keys):
            return child_fks

        return []

    def _effective_primary_keys(
        self,
        record,
    ) -> list[str]:
        if hasattr(record, "effective_primary_keys"):
            keys = record.effective_primary_keys()
        else:
            keys = list(getattr(record, "primary_keys", []) or [])

            if getattr(record, "primary_key", None):
                if record.primary_key not in keys:
                    keys.append(record.primary_key)

        return [
            key
            for key in keys
            if key
        ]

    def _effective_parent_keys(
        self,
        relationship,
    ) -> list[str]:
        if hasattr(relationship, "effective_parent_keys"):
            keys = relationship.effective_parent_keys()
        else:
            keys = list(getattr(relationship, "parent_keys", []) or [])

            if getattr(relationship, "parent_key", None):
                if relationship.parent_key not in keys:
                    keys.append(relationship.parent_key)

        return [
            key
            for key in keys
            if key
        ]

    def _effective_child_fks(
        self,
        relationship,
    ) -> list[str]:
        if hasattr(relationship, "effective_child_fks"):
            keys = relationship.effective_child_fks()
        else:
            keys = list(getattr(relationship, "child_fks", []) or [])

            if getattr(relationship, "child_fk", None):
                if relationship.child_fk not in keys:
                    keys.append(relationship.child_fk)

        return [
            key
            for key in keys
            if key
        ]

    def _extract_key_list(
        self,
        source: dict,
        plural_keys: list[str],
        single_keys: list[str],
    ) -> list[str]:
        values: list[str] = []

        for key in plural_keys:
            raw_value = source.get(key)

            if raw_value is None:
                continue

            if isinstance(raw_value, list):
                for item in raw_value:
                    normalized = self._normalize_name(item)

                    if normalized and normalized not in values:
                        values.append(normalized)
            else:
                normalized = self._normalize_name(raw_value)

                if normalized and normalized not in values:
                    values.append(normalized)

        for key in single_keys:
            raw_value = source.get(key)

            if raw_value is None:
                continue

            normalized = self._normalize_name(raw_value)

            if normalized and normalized not in values:
                values.append(normalized)

        return values

    def _token_matches(
        self,
        token: str,
        value: str,
    ) -> bool:
        token = token.upper()
        value = value.upper()

        return token in value or value in token

    def _upper_or_none(
        self,
        value: str | None,
    ) -> str | None:
        return value.upper() if value else None

    def _normalize_name(
        self,
        value,
    ) -> str:
        if value is None:
            return ""

        text = str(value).strip().upper()

        if not text:
            return ""

        text = text.replace("-", "_")
        text = text.replace(" ", "_")

        while "__" in text:
            text = text.replace("__", "_")

        return text.strip("_")

    def _remove_record_suffix(
        self,
        value: str,
    ) -> str:
        text = self._normalize_name(value)

        text = text.replace("-", "_")
        text = text.replace(" ", "_")

        text = text.upper()

        import re

        text = re.sub(
            r"_[0-9]{4}$",
            "",
            text,
        )

        text = re.sub(
            r"_479[A-Z0-9]+$",
            "",
            text,
        )

        return text