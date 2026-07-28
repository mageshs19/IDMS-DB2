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

    Generic behavior only:
    - No hardcoded record names.
    - No hardcoded column names.
    - No hardcoded SET names.

    Rules:
    - Use physical record.fields for DDL-safe columns.
    - Use record.mapping_fields only to understand group / subgroup structure.
    - Skip inner date parts.
    - Consolidate complete date parts into one DATE column.
    - Skip non-date group wrappers.
    - If CALC primary key references a group, expand it to child physical fields.
    - If no CALC exists, DB2MappingService generates ID_RECORD_<record_name> CHAR(20).
    - Preserve SET owner/member relationships.
    """

    def build(
        self,
        metadata,
    ) -> CanonicalSchema:
        schema = CanonicalSchema()

        for record in getattr(metadata, "records", []) or []:
            canonical_record = CanonicalRecord(
                name=NameNormalizer.normalize(
                    getattr(record, "name", "") or "",
                ),
                primary_key=(
                    NameNormalizer.normalize(
                        getattr(record, "primary_key", "") or "",
                    )
                    if getattr(record, "primary_key", None)
                    else None
                ),
                primary_keys=[],
            )

            physical_fields = getattr(record, "fields", []) or []

            normalized_fields = DateFieldConsolidator.consolidate(
                physical_fields,
            )

            added_fields: set[str] = set()

            for field in normalized_fields:
                field_name = NameNormalizer.normalize(
                    getattr(field, "name", "") or "",
                )

                if not field_name:
                    continue

                if self.is_date_part_name(field_name=field_name):
                    continue

                if field_name in added_fields:
                    continue

                if self.is_non_physical_group_field(field=field):
                    continue

                adjusted_field = self.adjust_occurs_field(
                    field=field,
                )

                canonical_record.fields.append(
                    CanonicalField(
                        name=field_name,
                        datatype=getattr(adjusted_field, "datatype", None),
                        length=getattr(adjusted_field, "length", None),
                        scale=getattr(adjusted_field, "scale", None),
                        occurs=getattr(adjusted_field, "occurs", False),
                        occurs_max=getattr(adjusted_field, "occurs_max", None),
                    )
                )

                added_fields.add(field_name)

            self.apply_primary_key_rules(
                canonical_record=canonical_record,
                record=record,
                added_fields=added_fields,
            )

            schema.records.append(canonical_record)

        self.add_sets_and_relationships(
            schema=schema,
            metadata=metadata,
        )

        return schema

    def apply_primary_key_rules(
        self,
        canonical_record: CanonicalRecord,
        record,
        added_fields: set[str],
    ) -> None:
        primary_key = canonical_record.primary_key

        if not primary_key:
            canonical_record.primary_keys = []
            return

        primary_key_fields = self.resolve_primary_key_fields(
            record=record,
            primary_key=primary_key,
        )

        if not primary_key_fields:
            self.ensure_primary_key_column(
                canonical_record=canonical_record,
                record=record,
                added_fields=added_fields,
            )

            if canonical_record.primary_key:
                canonical_record.primary_keys = [canonical_record.primary_key]

            return

        canonical_primary_keys: list[str] = []

        for key_field in primary_key_fields:
            key_name = NameNormalizer.normalize(
                getattr(key_field, "name", "") or "",
            )

            if not key_name:
                continue

            if key_name in canonical_primary_keys:
                continue

            canonical_primary_keys.append(key_name)

            if key_name in added_fields:
                continue

            datatype = self.datatype_for_key_field(
                key_field=key_field,
                record=record,
            )

            length = self.length_for_key_field(
                key_field=key_field,
                record=record,
            )

            scale = getattr(key_field, "scale", None)

            canonical_record.fields.append(
                CanonicalField(
                    name=key_name,
                    datatype=datatype,
                    length=length,
                    scale=scale,
                    occurs=False,
                    occurs_max=None,
                )
            )

            added_fields.add(key_name)

        canonical_record.primary_keys = canonical_primary_keys

        if canonical_primary_keys:
            canonical_record.primary_key = canonical_primary_keys[0]

    def resolve_primary_key_fields(
        self,
        record,
        primary_key: str,
    ) -> list:
        key_field = self.find_field_for_primary_key(
            record=record,
            primary_key=primary_key,
        )

        if key_field is None:
            return []

        if self.is_group_like_field(field=key_field):
            child_fields = self.child_physical_fields_for_group(
                record=record,
                group_field=key_field,
            )

            if child_fields:
                return child_fields

        return [key_field]

    def child_physical_fields_for_group(
        self,
        record,
        group_field,
    ) -> list:
        fields = getattr(record, "mapping_fields", []) or []

        if not fields:
            return []

        group_name = NameNormalizer.normalize(
            getattr(group_field, "name", "") or "",
        )

        group_level = getattr(group_field, "level", None)

        if group_level is None:
            return []

        try:
            group_level_int = int(group_level)
        except Exception:
            return []

        collecting = False
        children = []

        for field in fields:
            field_name = NameNormalizer.normalize(
                getattr(field, "name", "") or "",
            )

            field_level = getattr(field, "level", None)

            if field_level is None:
                continue

            try:
                field_level_int = int(field_level)
            except Exception:
                continue

            if not collecting:
                if field_name == group_name:
                    collecting = True
                continue

            if field_level_int <= group_level_int:
                break

            if self.is_non_physical_group_field(field=field):
                continue

            if self.is_date_part_name(field_name=field_name):
                continue

            if self.is_filler_field(field=field):
                continue

            if not self.has_physical_definition(field=field):
                continue

            children.append(field)

        return children

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
            canonical_record.primary_keys = [primary_key]
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
                    scale=getattr(key_field, "scale", None),
                    occurs=False,
                    occurs_max=None,
                )
            )

            added_fields.add(primary_key)
            canonical_record.primary_keys = [primary_key]
            return

        canonical_record.fields.append(
            CanonicalField(
                name=primary_key,
                datatype="CHAR",
                length=20,
                scale=None,
                occurs=False,
                occurs_max=None,
            )
        )

        added_fields.add(primary_key)
        canonical_record.primary_keys = [primary_key]

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

        normalized_primary_key = NameNormalizer.normalize(
            primary_key,
        )

        for field in fields:
            if NameNormalizer.normalize(getattr(field, "name", "") or "") == normalized_primary_key:
                return field

        suffix_removed_primary_key = self.remove_record_suffix(
            normalized_primary_key,
        )

        for field in fields:
            normalized_field_name = NameNormalizer.normalize(
                getattr(field, "name", "") or "",
            )

            if self.remove_record_suffix(normalized_field_name) == suffix_removed_primary_key:
                return field

        return None

    def datatype_for_key_field(
        self,
        key_field,
        record,
    ) -> str:
        datatype = getattr(key_field, "datatype", None)

        if datatype:
            return datatype

        picture = str(
            getattr(key_field, "picture", "") or ""
        ).upper()

        if "X" in picture:
            return "CHAR"

        if "9" in picture:
            return "DECIMAL"

        if self.is_group_like_field(field=key_field):
            return "CHAR"

        return "CHAR"

    def length_for_key_field(
        self,
        key_field,
        record,
    ) -> int | None:
        length = getattr(key_field, "length", None)

        if length:
            try:
                return int(length)
            except Exception:
                pass

        if self.is_group_like_field(field=key_field):
            return self.group_length(
                key_field=key_field,
                fields=getattr(record, "mapping_fields", []) or [],
            )

        return 20

    def group_length(
        self,
        key_field,
        fields,
    ) -> int:
        level = getattr(key_field, "level", None)

        if level is None:
            return 20

        try:
            group_level = int(level)
        except Exception:
            return 20

        key_name = NameNormalizer.normalize(
            getattr(key_field, "name", "") or "",
        )

        collecting = False
        total = 0

        for field in fields or []:
            field_name = NameNormalizer.normalize(
                getattr(field, "name", "") or "",
            )

            field_level = getattr(field, "level", None)

            if field_level is None:
                continue

            try:
                field_level_int = int(field_level)
            except Exception:
                continue

            if not collecting:
                if field_name == key_name:
                    collecting = True
                continue

            if field_level_int <= group_level:
                break

            if self.is_non_physical_group_field(field=field):
                continue

            length = getattr(field, "length", None)

            try:
                if length:
                    total += int(length)
            except Exception:
                continue

        return total if total > 0 else 20

    def adjust_occurs_field(
        self,
        field,
    ):
        occurs = getattr(field, "occurs", False)
        occurs_max = getattr(field, "occurs_max", None)

        if not occurs or not occurs_max:
            return field

        length = getattr(field, "length", None)

        if length is None:
            return field

        try:
            adjusted_length = int(length) * int(occurs_max)
        except Exception:
            return field

        try:
            return field.model_copy(
                update={
                    "length": adjusted_length,
                }
            )
        except Exception:
            try:
                field.length = adjusted_length
            except Exception:
                pass

            return field

    def is_non_physical_group_field(
        self,
        field,
    ) -> bool:
        if getattr(field, "datatype", None) == "DATE":
            return False

        if getattr(field, "basetype", None) == "DATE":
            return False

        if getattr(field, "is_group", False):
            return True

        if getattr(field, "has_child", False):
            return True

        if self.is_group_like_field(field=field) and not self.has_physical_definition(field=field):
            return True

        return False

    def is_group_like_field(
        self,
        field,
    ) -> bool:
        return bool(
            getattr(field, "is_group", False)
            or getattr(field, "has_child", False)
        )

    def has_physical_definition(
        self,
        field,
    ) -> bool:
        if getattr(field, "picture", None):
            return True

        if getattr(field, "datatype", None):
            return True

        if getattr(field, "length", None):
            return True

        return False

    def is_filler_field(
        self,
        field,
    ) -> bool:
        return str(
            getattr(field, "name", "") or ""
        ).upper().startswith("FILLER")

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

        normalized = normalized.replace(" ", "_")

        return __import__("re").sub(
            r"_[0-9]{4}$",
            "",
            normalized,
        )

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

            added_relationships.add(key)

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