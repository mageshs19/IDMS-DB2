import re
from idms_db2_converter.models import CobolAnalysis, Column, Relationship, SchemaModel


class SchemaValidator:
    """
    Validates and enriches schema references used by COBOL.

    This validator intentionally performs generic inference:
    - Infers missing primary keys from field names.
    - Infers missing set relationships from set-name tokens and COBOL usage.
    - Does not hard-code application-specific record or set names.
    """

    def validate(self, schema: SchemaModel, analysis: CobolAnalysis) -> list[str]:
        errors = []

        self._ensure_primary_keys(schema)

        for record in analysis.idms_records:
            if record not in schema.records:
                errors.append(
                    f"COBOL references record {record}, but schema does not define it."
                )

        for record in analysis.obtain_calc_records:
            if record not in schema.records:
                errors.append(f"OBTAIN CALC references missing record {record}.")
                continue

            if not schema.records[record].primary_key:
                self._infer_primary_key_for_record(schema, record)

            if not schema.records[record].primary_key:
                errors.append(f"OBTAIN CALC record {record} has no primary key.")

        for record_name, set_name in analysis.obtain_next:
            self._validate_set(
                schema=schema,
                set_name=set_name,
                errors=errors,
                expected_child_record=record_name,
            )

        for set_name in analysis.obtain_owner_sets:
            self._validate_set(
                schema=schema,
                set_name=set_name,
                errors=errors,
                expected_child_record=None,
            )

        for set_name in analysis.find_first_sets:
            self._validate_set(
                schema=schema,
                set_name=set_name,
                errors=errors,
                expected_child_record=None,
            )

        return errors

    def _ensure_primary_keys(self, schema: SchemaModel) -> None:
        for record_name in list(schema.records.keys()):
            self._infer_primary_key_for_record(schema, record_name)

    def _infer_primary_key_for_record(
        self,
        schema: SchemaModel,
        record_name: str,
    ) -> None:
        if record_name not in schema.records:
            return

        record = schema.records[record_name]

        if record.primary_key:
            if record.primary_key in record.fields:
                record.fields[record.primary_key].nullable = False
            return

        candidate = self._find_primary_key_candidate(
            record_name=record_name,
            fields=set(record.fields.keys()),
        )

        if candidate:
            record.primary_key = candidate
            record.fields[candidate].nullable = False
            return

        if record.fields:
            first_field = next(iter(record.fields.keys()))
            record.primary_key = first_field
            record.fields[first_field].nullable = False

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

        if not rel.parent_key:
            self._infer_primary_key_for_record(schema, rel.parent_record)
            rel.parent_key = schema.records[rel.parent_record].primary_key

        if not rel.child_fk:
            rel.child_fk = self._infer_child_fk(
                schema=schema,
                parent_record=rel.parent_record,
                child_record=rel.child_record,
                parent_key=rel.parent_key,
            )

        if not rel.parent_key:
            errors.append(f"Set {set_name} has no parent_key.")

        if not rel.child_fk:
            errors.append(f"Set {set_name} has no child_fk.")

        if rel.parent_key and rel.parent_key not in schema.records[rel.parent_record].fields:
            self._add_field_like_parent_key(
                schema=schema,
                target_record=rel.parent_record,
                source_record=rel.parent_record,
                source_key=rel.parent_key,
                target_field=rel.parent_key,
                nullable=False,
            )

        if rel.child_fk and rel.child_fk not in schema.records[rel.child_record].fields:
            self._add_field_like_parent_key(
                schema=schema,
                target_record=rel.child_record,
                source_record=rel.parent_record,
                source_key=rel.parent_key,
                target_field=rel.child_fk,
                nullable=True,
            )

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

        self._infer_primary_key_for_record(schema, parent_record)

        parent_key = schema.records[parent_record].primary_key

        if not parent_key:
            return None

        child_fk = self._infer_child_fk(
            schema=schema,
            parent_record=parent_record,
            child_record=child_record,
            parent_key=parent_key,
        )

        if not child_fk:
            child_fk = parent_key

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
            parent_key=parent_key,
            child_fk=child_fk,
            order_by=[child_fk],
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
            score = self._score_record_against_tokens(record_name, set_tokens)

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

            score = self._score_record_against_tokens(record_name, set_tokens)

            if score > best_score:
                best_score = score
                best_record = record_name

        return best_record if best_score > 0 else None

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
                return field_name

        return None

    def _add_field_like_parent_key(
        self,
        schema: SchemaModel,
        target_record: str,
        source_record: str,
        source_key: str | None,
        target_field: str,
        nullable: bool,
    ) -> None:
        if not source_key:
            return

        if source_record not in schema.records:
            return

        source = schema.records[source_record]
        target = schema.records[target_record]

        source_column = source.fields.get(source_key)

        if source_column:
            target.fields[target_field] = Column(
                name=target_field,
                datatype=source_column.datatype,
                length=source_column.length,
                scale=source_column.scale,
                nullable=nullable,
            )
        else:
            target.fields[target_field] = Column(
                name=target_field,
                datatype="CHAR",
                length=12,
                scale=None,
                nullable=nullable,
            )

    def _score_record_against_tokens(
        self,
        record_name: str,
        tokens: list[str],
    ) -> int:
        normalized_record = self._normalize(record_name)
        compact_record = self._compact(record_name)

        score = 0

        for token in tokens:
            normalized_token = self._normalize(token)
            compact_token = self._compact(token)

            if normalized_token == normalized_record:
                score += 20
                continue

            if normalized_record.startswith(normalized_token):
                score += 10
                continue

            if normalized_token.startswith(normalized_record):
                score += 10
                continue

            if compact_token and compact_record.startswith(compact_token):
                score += 6
                continue

            if compact_token and compact_token in compact_record:
                score += 4
                continue

            if normalized_token[:3] and normalized_record.startswith(normalized_token[:3]):
                score += 2

        return score

    def _tokens(self, value: str) -> list[str]:
        normalized = self._normalize(value)

        return [
            token
            for token in normalized.split("_")
            if token
        ]

    def _normalize(self, value: str) -> str:
        return value.upper().replace("-", "_")

    def _compact(self, value: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", self._normalize(value))