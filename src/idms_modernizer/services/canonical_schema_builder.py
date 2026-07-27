from idms_modernizer.domain.canonical_models import (
    CanonicalSchema,
    CanonicalRecord,
    CanonicalField,
    CanonicalSet,
    CanonicalRelationship,
)
from idms_modernizer.services.name_normalizer import (
    NameNormalizer,
)
from idms_modernizer.services.date_field_consolidator import (
    DateFieldConsolidator,
)


class CanonicalSchemaBuilder:
    """
    Builds canonical schema from IDMS metadata.

    DDL rules:
    - Use leaf fields by default.
    - Skip inner date parts.
    - Consolidate complete date parts into one DATE column.
    - Skip non-date group wrappers.
    - Add CALC group key columns when primary_key references a group.
    - Ensure primary key column always exists.
    - Flatten OCCURS fields using effective max length.
    """

    def build(
        self,
        metadata,
    ) -> CanonicalSchema:
        schema = CanonicalSchema()

        for record in metadata.records:
            print(
                f"CanonicalBuilder Input: "
                f"{record.name} "
                f"PK={record.primary_key}"
            )

            canonical_record = CanonicalRecord(
                name=NameNormalizer.normalize(
                    record.name,
                ),
                primary_key=(
                    NameNormalizer.normalize(
                        record.primary_key,
                    )
                    if record.primary_key
                    else None
                ),
            )

            print(
                f"CanonicalRecord Created: "
                f"{canonical_record.name} "
                f"PK={canonical_record.primary_key}"
            )

            physical_fields = getattr(
                record,
                "fields",
                [],
            ) or []

            normalized_fields = DateFieldConsolidator.consolidate(
                physical_fields,
            )

            added_fields: set[str] = set()

            for field in normalized_fields:
                field_name = NameNormalizer.normalize(
                    field.name,
                )

                if not field_name:
                    continue

                if self.is_date_part_name(
                    field_name=field_name,
                ):
                    continue

                if field_name in added_fields:
                    continue

                if self.is_non_physical_group_field(
                    field=field,
                ):
                    continue

                adjusted_field = self.adjust_occurs_field(
                    field=field,
                )

                canonical_record.fields.append(
                    CanonicalField(
                        name=field_name,
                        datatype=adjusted_field.datatype,
                        length=adjusted_field.length,
                        scale=adjusted_field.scale,
                        occurs=getattr(adjusted_field, "occurs", False),
                        occurs_max=getattr(adjusted_field, "occurs_max", None),
                    )
                )

                added_fields.add(
                    field_name,
                )

            self.ensure_primary_key_column(
                canonical_record=canonical_record,
                record=record,
                added_fields=added_fields,
            )

            schema.records.append(
                canonical_record,
            )

        self.add_sets_and_relationships(
            schema=schema,
            metadata=metadata,
        )

        return schema

    def is_non_physical_group_field(
        self,
        field,
    ) -> bool:
        is_group = bool(
            getattr(field, "is_group", False)
            or getattr(field, "has_child", False)
        )

        if not is_group:
            return False

        datatype = (
            getattr(field, "datatype", None)
            or ""
        ).upper()

        basetype = (
            getattr(field, "basetype", None)
            or ""
        ).upper()

        if datatype == "DATE" or basetype == "DATE":
            return False

        return True

    def ensure_primary_key_column(
        self,
        canonical_record: CanonicalRecord,
        record,
        added_fields: set[str],
    ) -> None:
        primary_key = canonical_record.primary_key

        if not primary_key:
            return

        if primary_key in added_fields:
            return

        key_field = self.find_field_for_primary_key(
            record=record,
            primary_key=primary_key,
        )

        if key_field is not None:
            datatype = self.datatype_for_key_field(
                key_field=key_field,
                record=record,
            )

            length = self.length_for_key_field(
                key_field=key_field,
                record=record,
            )

            canonical_record.fields.append(
                CanonicalField(
                    name=primary_key,
                    datatype=datatype,
                    length=length,
                    scale=None,
                    occurs=False,
                    occurs_max=None,
                )
            )

            added_fields.add(
                primary_key,
            )

            return

        canonical_record.fields.append(
            CanonicalField(
                name=primary_key,
                datatype="VARCHAR",
                length=255,
                scale=None,
                occurs=False,
                occurs_max=None,
            )
        )

        added_fields.add(
            primary_key,
        )

    def find_field_for_primary_key(
        self,
        record,
        primary_key: str,
    ):
        fields = []

        fields.extend(
            getattr(record, "fields", []) or []
        )

        fields.extend(
            getattr(record, "mapping_fields", []) or []
        )

        for field in fields:
            if NameNormalizer.normalize(field.name) == primary_key:
                return field

        suffix_removed_primary_key = self.remove_record_suffix(
            primary_key,
        )

        for field in fields:
            field_name = NameNormalizer.normalize(
                field.name,
            )

            if self.remove_record_suffix(field_name) == suffix_removed_primary_key:
                return field

        return None

    def datatype_for_key_field(
        self,
        key_field,
        record,
    ) -> str:
        datatype = (
            getattr(
                key_field,
                "datatype",
                None,
            )
            or ""
        ).upper()

        if datatype:
            return datatype

        if (
            getattr(key_field, "is_group", False)
            or getattr(key_field, "has_child", False)
        ):
            return "VARCHAR"

        return "VARCHAR"

    def length_for_key_field(
        self,
        key_field,
        record,
    ) -> int | None:
        length = getattr(
            key_field,
            "length",
            None,
        )

        if length:
            return int(length)

        if (
            getattr(key_field, "is_group", False)
            or getattr(key_field, "has_child", False)
        ):
            return self.group_length(
                key_field=key_field,
                fields=getattr(record, "mapping_fields", []) or [],
            )

        return 255

    def group_length(
        self,
        key_field,
        fields,
    ) -> int:
        level = getattr(
            key_field,
            "level",
            None,
        )

        if level is None:
            return 255

        try:
            parent_level = int(
                level,
            )
        except Exception:
            return 255

        started = False
        total = 0

        key_name = NameNormalizer.normalize(
            getattr(key_field, "name", ""),
        )

        for candidate in fields:
            candidate_name = NameNormalizer.normalize(
                getattr(candidate, "name", ""),
            )

            if candidate is key_field or candidate_name == key_name:
                started = True
                continue

            if not started:
                continue

            candidate_level = getattr(
                candidate,
                "level",
                None,
            )

            if candidate_level is None:
                continue

            try:
                child_level = int(
                    candidate_level,
                )
            except Exception:
                continue

            if child_level <= parent_level:
                break

            if getattr(candidate, "has_child", False):
                continue

            child_length = self.effective_field_length(
                field=candidate,
            )

            if not child_length:
                continue

            total += child_length

        return total if total > 0 else 255

    def adjust_occurs_field(
        self,
        field,
    ):
        occurs = getattr(
            field,
            "occurs",
            False,
        )

        occurs_max = getattr(
            field,
            "occurs_max",
            None,
        )

        if not occurs or not occurs_max:
            return field

        total_length = self.effective_field_length(
            field=field,
        )

        if not total_length:
            return field

        return field.model_copy(
            update={
                "datatype": "VARCHAR",
                "length": total_length,
                "scale": None,
            }
        )

    def effective_field_length(
        self,
        field,
    ) -> int | None:
        length = getattr(
            field,
            "length",
            None,
        )

        occurs_max = getattr(
            field,
            "occurs_max",
            None,
        )

        start_position = getattr(
            field,
            "start_position",
            None,
        )

        end_position = getattr(
            field,
            "end_position",
            None,
        )

        physical_length = None

        if start_position is not None and end_position is not None:
            try:
                physical_length = int(end_position) - int(start_position) + 1
            except Exception:
                physical_length = None

        numeric_length = None

        if length is not None:
            try:
                numeric_length = int(length)
            except Exception:
                numeric_length = None

        expanded_length = None

        if occurs_max and numeric_length:
            try:
                expanded_length = int(occurs_max) * int(numeric_length)
            except Exception:
                expanded_length = None

        candidates = [
            value
            for value in [
                physical_length,
                expanded_length,
                numeric_length,
            ]
            if value is not None and value > 0
        ]

        if not candidates:
            return None

        return max(candidates)

    def is_date_part_name(
        self,
        field_name: str,
    ) -> bool:
        return DateFieldConsolidator.parse_date_part(
            field_name=field_name,
        ) is not None

    def remove_record_suffix(
        self,
        field_name: str,
    ) -> str:
        normalized = NameNormalizer.normalize(
            field_name,
        )

        parts = normalized.split()

        if (
            len(parts) > 1
            and parts[-1].isdigit()
            and len(parts[-1]) == 4
        ):
            return " ".join(
                parts[:-1],
            )

        return normalized

    def add_sets_and_relationships(
        self,
        schema: CanonicalSchema,
        metadata,
    ) -> None:
        added_relationships = set()

        for rel in getattr(metadata, "relationships", []) or []:
            set_name = getattr(rel, "set_name", None)
            owner_record = getattr(rel, "owner_record", None)
            member_record = getattr(rel, "member_record", None)

            if not set_name or not owner_record or not member_record:
                continue

            normalized_set_name = NameNormalizer.normalize(
                set_name,
            )

            normalized_owner = NameNormalizer.normalize(
                owner_record,
            )

            normalized_member = NameNormalizer.normalize(
                member_record,
            )

            key = (
                normalized_owner,
                normalized_member,
                normalized_set_name,
            )

            if key in added_relationships:
                continue

            added_relationships.add(
                key,
            )

            schema.sets.append(
                CanonicalSet(
                    name=normalized_set_name,
                    owner_record=normalized_owner,
                    member_record=normalized_member,
                )
            )

            schema.relationships.append(
                CanonicalRelationship(
                    set_name=normalized_set_name,
                    parent_record=normalized_owner,
                    child_record=normalized_member,
                    cardinality="1:N",
                )
            )