import re

from idms_db2_converter.models import (
    CobolAnalysis,
    Column,
    Relationship,
    SchemaModel,
)


class SchemaValidator:
    """
    Validates and enriches schema references used by COBOL.

    Composite-key support:
    - Uses record.effective_primary_keys() when available.
    - Uses relationship.effective_parent_keys() and effective_child_fks().
    - Preserves parent_key / child_fk as first key for backward compatibility.
    - Preserves parent_keys / child_fks for composite relationships.
    - Adds missing parent/child key columns when inferred.
    """

    def validate(
        self,
        schema: SchemaModel,
        analysis: CobolAnalysis,
    ) -> list[str]:
        errors: list[str] = []

        self._ensure_primary_keys(schema)

        for record in getattr(analysis, "idms_records", []) or []:
            if record not in schema.records:
                errors.append(
                    f"COBOL references record {record}, but schema does not define it."
                )

        for record in getattr(analysis, "obtain_calc_records", []) or []:
            if record not in schema.records:
                errors.append(
                    f"OBTAIN CALC references missing record {record}."
                )
                continue

            self._infer_primary_key_for_record(
                schema=schema,
                record_name=record,
            )

            primary_keys = self._effective_primary_keys(
                schema.records[record],
            )

            if not primary_keys:
                errors.append(
                    f"OBTAIN CALC record {record} has no primary key."
                )

            for primary_key in primary_keys:
                if primary_key not in schema.records[record].fields:
                    errors.append(
                        f"OBTAIN CALC record {record} primary key {primary_key} is not declared as a column."
                    )

        for record_name, set_name in getattr(analysis, "obtain_next", []) or []:
            self._validate_set(
                schema=schema,
                set_name=set_name,
                errors=errors,
                expected_child_record=record_name,
            )

        for set_name in getattr(analysis, "obtain_owner_sets", []) or []:
            self._validate_set(
                schema=schema,
                set_name=set_name,
                errors=errors,
                expected_child_record=None,
            )

        for set_name in getattr(analysis, "find_first_sets", []) or []:
            self._validate_set(
                schema=schema,
                set_name=set_name,
                errors=errors,
                expected_child_record=None,
            )

        return errors

    def _ensure_primary_keys(
        self,
        schema: SchemaModel,
    ) -> None:
        for record_name in list(schema.records.keys()):
            self._infer_primary_key_for_record(
                schema=schema,
                record_name=record_name,
            )

    def _infer_primary_key_for_record(
        self,
        schema: SchemaModel,
        record_name: str,
    ) -> None:
        if record_name not in schema.records:
            return

        record = schema.records[record_name]

        primary_keys = self._effective_primary_keys(record)

        if primary_keys:
            cleaned = []

            for key in primary_keys:
                if key not in record.fields:
                    continue

                if key in cleaned:
                    continue

                cleaned.append(key)
                record.fields[key].nullable = False
                record.fields[key].primary_key = True

            if cleaned:
                self._set_primary_keys(
                    record=record,
                    keys=cleaned,
                )
                return

        candidate = self._find_primary_key_candidate(
            record_name=record_name,
            fields=set(record.fields.keys()),
        )

        if candidate:
            self._set_primary_keys(
                record=record,
                keys=[candidate],
            )
            return

        if record.fields:
            first_field = next(iter(record.fields.keys()))
            self._set_primary_keys(
                record=record,
                keys=[first_field],
            )

    def _find_primary_key_candidate(
        self,
        record_name: str,
        fields: set[str],
    ) -> str | None:
        normalized_record = self._normalize(record_name)
        compact_record = self._compact(normalized_record)

        direct_candidates = [
            f"{normalized_record}_ID",
            f"{normalized_record}_CODE",
        ]

        for candidate in direct_candidates:
            if candidate in fields:
                return candidate

        for field in fields:
            normalized_field = self._normalize(field)
            compact_field = self._compact(normalized_field)

            if normalized_field.endswith("_ID") and compact_record in compact_field:
                return field

            if normalized_field.endswith("_CODE") and compact_record in compact_field:
                return field

        id_fields = [
            field
            for field in fields
            if self._normalize(field).endswith("_ID")
        ]

        if len(id_fields) == 1:
            return id_fields[0]

        code_fields = [
            field
            for field in fields
            if self._normalize(field).endswith("_CODE")
        ]

        if len(code_fields) == 1:
            return code_fields[0]

        return None

    def _validate_set(
        self,
        schema: SchemaModel,
        set_name: str,
        errors: list[str],
        expected_child_record: str | None,
    ) -> None:
        set_name = set_name.upper()

        if set_name not in schema.relationships:
            inferred = self._infer_relationship(
                schema=schema,
                set_name=set_name,
                expected_child_record=expected_child_record,
            )

            if inferred:
                schema.relationships[set_name] = inferred
            else:
                errors.append(
                    f"COBOL references set {set_name}, but schema relationships do not define it."
                )
                return

        rel = schema.relationships[set_name]

        if rel.parent_record not in schema.records:
            errors.append(
                f"Set {set_name} parent record {rel.parent_record} is missing."
            )
            return

        if rel.child_record not in schema.records:
            errors.append(
                f"Set {set_name} child record {rel.child_record} is missing."
            )
            return

        parent_record = schema.records[rel.parent_record]
        child_record = schema.records[rel.child_record]

        self._infer_primary_key_for_record(
            schema=schema,
            record_name=rel.parent_record,
        )

        parent_keys = self._effective_parent_keys(rel)

        if not parent_keys:
            parent_keys = self._effective_primary_keys(parent_record)

        if not parent_keys:
            errors.append(
                f"Set {set_name} has no parent_key or parent_keys."
            )
            return

        child_fks = self._effective_child_fks(rel)

        if not child_fks:
            child_fks = self._infer_child_fks(
                schema=schema,
                parent_record=rel.parent_record,
                child_record=rel.child_record,
                parent_keys=parent_keys,
            )

        if not child_fks:
            child_fks = parent_keys.copy()

        if len(parent_keys) != len(child_fks):
            errors.append(
                f"Set {set_name} has mismatched composite key counts: "
                f"{len(parent_keys)} parent key(s), {len(child_fks)} child FK(s)."
            )
            return

        self._set_relationship_keys(
            relationship=rel,
            parent_keys=parent_keys,
            child_fks=child_fks,
        )

        for parent_key in parent_keys:
            if parent_key not in parent_record.fields:
                self._add_field_like_parent_key(
                    schema=schema,
                    target_record=rel.parent_record,
                    source_record=rel.parent_record,
                    source_key=parent_key,
                    target_field=parent_key,
                    nullable=False,
                )

        for parent_key, child_fk in zip(parent_keys, child_fks):
            if child_fk not in child_record.fields:
                self._add_field_like_parent_key(
                    schema=schema,
                    target_record=rel.child_record,
                    source_record=rel.parent_record,
                    source_key=parent_key,
                    target_field=child_fk,
                    nullable=True,
                )

        if not rel.order_by:
            rel.order_by = child_fks.copy()

    def _infer_relationship(
        self,
        schema: SchemaModel,
        set_name: str,
        expected_child_record: str | None,
    ) -> Relationship | None:
        child_record = self._infer_child_record(
            schema=schema,
            set_name=set_name,
            expected_child_record=expected_child_record,
        )

        if not child_record:
            return None

        parent_record = self._infer_parent_record(
            schema=schema,
            set_name=set_name,
            child_record=child_record,
        )

        if not parent_record:
            return None

        self._infer_primary_key_for_record(
            schema=schema,
            record_name=parent_record,
        )

        parent = schema.records[parent_record]
        parent_keys = self._effective_primary_keys(parent)

        if not parent_keys:
            return None

        child_fks = self._infer_child_fks(
            schema=schema,
            parent_record=parent_record,
            child_record=child_record,
            parent_keys=parent_keys,
        )

        if not child_fks:
            child_fks = parent_keys.copy()

        if len(parent_keys) != len(child_fks):
            return None

        for parent_key, child_fk in zip(parent_keys, child_fks):
            if child_fk not in schema.records[child_record].fields:
                self._add_field_like_parent_key(
                    schema=schema,
                    target_record=child_record,
                    source_record=parent_record,
                    source_key=parent_key,
                    target_field=child_fk,
                    nullable=True,
                )

        return Relationship(
            set_name=set_name,
            parent_record=parent_record,
            child_record=child_record,
            cardinality="1:N",
            parent_key=parent_keys[0] if parent_keys else None,
            child_fk=child_fks[0] if child_fks else None,
            parent_keys=parent_keys,
            child_fks=child_fks,
            order_by=child_fks.copy(),
        )

    def _infer_child_record(
        self,
        schema: SchemaModel,
        set_name: str,
        expected_child_record: str | None,
    ) -> str | None:
        if expected_child_record and expected_child_record in schema.records:
            return expected_child_record

        set_tokens = self._tokens(set_name)

        best_score = 0
        best_record = None

        for record_name in schema.records:
            score = self._score_record_against_tokens(
                record_name,
                set_tokens,
            )

            if score > best_score:
                best_score = score
                best_record = record_name

        return best_record if best_score > 0 else None

    def _infer_parent_record(
        self,
        schema: SchemaModel,
        set_name: str,
        child_record: str,
    ) -> str | None:
        set_tokens = self._tokens(set_name)

        best_score = 0
        best_record = None

        for record_name in schema.records:
            if record_name == child_record:
                continue

            score = self._score_record_against_tokens(
                record_name,
                set_tokens,
            )

            if score > best_score:
                best_score = score
                best_record = record_name

        return best_record if best_score > 0 else None

    def _infer_child_fks(
        self,
        schema: SchemaModel,
        parent_record: str,
        child_record: str,
        parent_keys: list[str],
    ) -> list[str]:
        result: list[str] = []
        child = schema.records[child_record]

        for parent_key in parent_keys:
            child_fk = self._infer_child_fk(
                schema=schema,
                parent_record=parent_record,
                child_record=child_record,
                parent_key=parent_key,
            )

            if child_fk:
                result.append(child_fk)

        if len(result) == len(parent_keys):
            return result

        parent_base_keys = {
            self._remove_record_suffix(parent_key): parent_key
            for parent_key in parent_keys
            if parent_key
        }

        result = []

        for parent_base_key, parent_key in parent_base_keys.items():
            matched_child_fk = None

            for child_field_name in child.fields:
                child_base_name = self._remove_record_suffix(child_field_name)

                if child_base_name == parent_base_key:
                    matched_child_fk = child_field_name
                    break

            if matched_child_fk:
                result.append(matched_child_fk)

        if len(result) == len(parent_keys):
            return result

        return []

    def _infer_child_fk(
        self,
        schema: SchemaModel,
        parent_record: str,
        child_record: str,
        parent_key: str | None,
    ) -> str | None:
        if not parent_key:
            return None

        child = schema.records[child_record]
        parent_key_norm = self._normalize(parent_key)

        if parent_key in child.fields:
            return parent_key

        if parent_key_norm in child.fields:
            return parent_key_norm

        parent_tokens = self._tokens(parent_record)
        key_suffixes = ["_ID", "_CODE"]

        for field_name in child.fields:
            normalized_field = self._normalize(field_name)

            if normalized_field == parent_key_norm:
                return field_name

            for token in parent_tokens:
                if normalized_field.startswith(token + "_"):
                    for suffix in key_suffixes:
                        if normalized_field.endswith(suffix):
                            return field_name

        parent_compact = self._compact(parent_record)

        for field_name in child.fields:
            compact_field = self._compact(field_name)

            if parent_compact and parent_compact in compact_field:
                if self._compact(parent_key) in compact_field:
                    return field_name

        return None

    def _add_field_like_parent_key(
        self,
        schema: SchemaModel,
        target_record: str,
        source_record: str,
        source_key: str,
        target_field: str,
        nullable: bool,
    ) -> None:
        if target_record not in schema.records:
            return

        if source_record not in schema.records:
            return

        source = schema.records[source_record]
        target = schema.records[target_record]

        source_column = source.fields.get(source_key)

        target.fields[target_field] = Column(
            name=target_field,
            datatype=source_column.datatype if source_column else "CHAR",
            length=source_column.length if source_column else 20,
            scale=source_column.scale if source_column else None,
            nullable=nullable,
            primary_key=False,
        )

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

    def _set_primary_keys(
        self,
        record,
        keys: list[str],
    ) -> None:
        cleaned: list[str] = []

        for key in keys or []:
            if not key:
                continue

            normalized = str(key).upper()

            if normalized in cleaned:
                continue

            cleaned.append(normalized)

        if hasattr(record, "set_primary_keys"):
            record.set_primary_keys(cleaned)
        else:
            record.primary_keys = cleaned
            record.primary_key = cleaned[0] if cleaned else None

            for key in cleaned:
                if key in record.fields:
                    record.fields[key].primary_key = True
                    record.fields[key].nullable = False

        for key in cleaned:
            if key in record.fields:
                record.fields[key].primary_key = True
                record.fields[key].nullable = False

    def _set_relationship_keys(
        self,
        relationship,
        parent_keys: list[str],
        child_fks: list[str],
    ) -> None:
        relationship.parent_keys = parent_keys.copy()
        relationship.child_fks = child_fks.copy()
        relationship.parent_key = parent_keys[0] if parent_keys else None
        relationship.child_fk = child_fks[0] if child_fks else None

    def _score_record_against_tokens(
        self,
        record_name: str,
        tokens: list[str],
    ) -> int:
        score = 0
        normalized_record = self._normalize(record_name)
        compact_record = self._compact(record_name)

        for token in tokens:
            normalized_token = self._normalize(token)
            compact_token = self._compact(token)

            if normalized_token == normalized_record:
                score += 5
                continue

            if normalized_token in normalized_record:
                score += 2

            if compact_token and compact_token in compact_record:
                score += 2

        return score

    def _tokens(
        self,
        value: str,
    ) -> list[str]:
        normalized = self._normalize(value)

        return [
            token
            for token in normalized.split("_")
            if token
        ]

    def _normalize(
        self,
        value: str,
    ) -> str:
        return str(value or "").upper().replace("-", "_").replace(" ", "_")

    def _compact(
        self,
        value: str,
    ) -> str:
        return re.sub(
            r"[^A-Z0-9]",
            "",
            self._normalize(value),
        )

    def _remove_record_suffix(
        self,
        value: str,
    ) -> str:
        normalized = self._normalize(value)

        normalized = re.sub(
            r"_[0-9]{4}$",
            "",
            normalized,
        )

        normalized = re.sub(
            r"_479[A-Z0-9]+$",
            "",
            normalized,
        )

        return normalized