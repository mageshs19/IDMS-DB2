import re

from idms_modernizer.domain.canonical_models import (
    CanonicalSchema,
    CanonicalRecord,
    CanonicalField,
    CanonicalSet,
    CanonicalRelationship,
)
from idms_modernizer.services.name_normalizer import NameNormalizer
from idms_modernizer.services.date_field_consolidator import DateFieldConsolidator


class CanonicalSchemaBuilder:
    """
    Builds canonical schema from IDMS metadata.

    Generic behavior only:
    - No hardcoded record names.
    - No hardcoded column names.
    - No hardcoded SET names.

    Rules:
    - Physical DB2 columns come from record.fields, after date consolidation.
    - Group detection uses mapping_fields level hierarchy.
    - CALC outer group is never a physical DB2 PK column.
    - CALC intermediate groups are not physical DB2 columns.
    - CALC physical non-date leaf children become actual composite PK columns.
    - Date group/date parts are never physical PK.
    - FILLER is never physical PK.
    - If no CALC exists, DB2MappingService creates ID_RECORD_<record_name> CHAR(20).
    """

    def build(self, metadata) -> CanonicalSchema:
        schema = CanonicalSchema()

        for record in getattr(metadata, "records", []) or []:
            record_name = NameNormalizer.normalize(getattr(record, "name", "") or "")

            primary_key = (
                NameNormalizer.normalize(getattr(record, "primary_key", "") or "")
                if getattr(record, "primary_key", None)
                else None
            )

            canonical_record = CanonicalRecord(
                name=record_name,
                primary_key=primary_key,
                primary_keys=[],
            )

            mapping_fields = (
                getattr(record, "mapping_fields", None)
                or getattr(record, "fields", None)
                or []
            )

            group_names = self.build_group_name_set(fields=mapping_fields)
            date_names = self.build_date_name_set(fields=mapping_fields)

            physical_fields = getattr(record, "fields", []) or []

            normalized_fields = DateFieldConsolidator.consolidate(
                physical_fields,
            )

            added_fields: set[str] = set()

            for field in normalized_fields:
                field_name = NameNormalizer.normalize(getattr(field, "name", "") or "")

                if not field_name:
                    continue

                if self.is_date_part_name(field_name):
                    continue

                if field_name in added_fields:
                    continue

                if field_name in group_names and field_name not in date_names:
                    continue

                if self.is_non_physical_group_field(field=field):
                    continue

                adjusted_field = self.adjust_occurs_field(field=field)

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
                group_names=group_names,
                date_names=date_names,
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
        group_names: set[str],
        date_names: set[str],
    ) -> None:
        primary_key = canonical_record.primary_key

        if not primary_key:
            canonical_record.primary_keys = []
            return

        primary_key_fields = self.resolve_primary_key_fields(
            record=record,
            primary_key=primary_key,
            group_names=group_names,
            date_names=date_names,
        )

        if not primary_key_fields:
            canonical_record.primary_keys = []
            canonical_record.primary_key = None
            return

        canonical_primary_keys: list[str] = []

        for key_field in primary_key_fields:
            key_name = NameNormalizer.normalize(getattr(key_field, "name", "") or "")

            if not key_name:
                continue

            if key_name in canonical_primary_keys:
                continue

            if key_name in date_names:
                continue

            if key_name in group_names:
                continue

            if self.is_date_part_name(key_name):
                continue

            if self.is_date_field(key_field):
                continue

            if self.is_filler_field(key_field):
                continue

            if not self.has_physical_definition(key_field):
                continue

            canonical_primary_keys.append(key_name)

            if key_name in added_fields:
                continue

            canonical_record.fields.append(
                CanonicalField(
                    name=key_name,
                    datatype=self.datatype_for_key_field(key_field),
                    length=self.length_for_key_field(key_field),
                    scale=getattr(key_field, "scale", None),
                    occurs=False,
                    occurs_max=None,
                )
            )

            added_fields.add(key_name)

        canonical_record.primary_keys = canonical_primary_keys

        if canonical_primary_keys:
            canonical_record.primary_key = canonical_primary_keys[0]
        else:
            canonical_record.primary_key = None

    def resolve_primary_key_fields(
        self,
        record,
        primary_key: str,
        group_names: set[str],
        date_names: set[str],
    ) -> list:
        mapping_fields = (
            getattr(record, "mapping_fields", None)
            or getattr(record, "fields", None)
            or []
        )

        key_field = self.find_field_for_primary_key(
            record=record,
            primary_key=primary_key,
        )

        if key_field is None:
            return []

        key_name = NameNormalizer.normalize(getattr(key_field, "name", "") or "")

        if key_name in group_names:
            return self.child_physical_fields_for_group(
                fields=mapping_fields,
                group_field=key_field,
                group_names=group_names,
                date_names=date_names,
            )

        if key_name in date_names:
            return []

        if self.is_date_field(key_field):
            return []

        if self.is_date_part_name(key_name):
            return []

        if self.is_filler_field(key_field):
            return []

        return [key_field]

    def child_physical_fields_for_group(
        self,
        fields,
        group_field,
        group_names: set[str],
        date_names: set[str],
    ) -> list:
        field_list = list(fields or [])

        if not field_list:
            return []

        group_name = NameNormalizer.normalize(getattr(group_field, "name", "") or "")
        group_level = getattr(group_field, "level", None)

        if group_level is None:
            return []

        try:
            group_level_int = int(group_level)
        except Exception:
            return []

        collecting = False
        children = []

        for field in field_list:
            field_name = NameNormalizer.normalize(getattr(field, "name", "") or "")
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

            if not field_name:
                continue

            if field_name in group_names:
                continue

            if field_name in date_names:
                continue

            if self.is_date_part_name(field_name):
                continue

            if self.is_date_field(field):
                continue

            if self.is_filler_field(field):
                continue

            if not self.has_physical_definition(field):
                continue

            children.append(field)

        return children

    def build_group_name_set(self, fields) -> set[str]:
        result: set[str] = set()
        field_list = list(fields or [])

        for index, field in enumerate(field_list):
            field_name = NameNormalizer.normalize(getattr(field, "name", "") or "")
            field_level = getattr(field, "level", None)

            if not field_name or field_level is None:
                continue

            try:
                field_level_int = int(field_level)
            except Exception:
                continue

            for next_field in field_list[index + 1:]:
                next_level = getattr(next_field, "level", None)

                if next_level is None:
                    continue

                try:
                    next_level_int = int(next_level)
                except Exception:
                    continue

                if next_level_int > field_level_int:
                    result.add(field_name)
                    break

                if next_level_int <= field_level_int:
                    break

        return result

    def build_date_name_set(self, fields) -> set[str]:
        result: set[str] = set()
        field_list = list(fields or [])

        for index, field in enumerate(field_list):
            field_name = NameNormalizer.normalize(getattr(field, "name", "") or "")
            field_level = getattr(field, "level", None)

            if not field_name:
                continue

            if self.is_date_part_name(field_name):
                result.add(field_name)
                continue

            if self.is_date_field(field):
                result.add(field_name)
                continue

            if field_level is None:
                continue

            try:
                field_level_int = int(field_level)
            except Exception:
                continue

            descendants = []

            for next_field in field_list[index + 1:]:
                next_level = getattr(next_field, "level", None)

                if next_level is None:
                    continue

                try:
                    next_level_int = int(next_level)
                except Exception:
                    continue

                if next_level_int <= field_level_int:
                    break

                descendants.append(next_field)

            parts_found = set()

            for descendant in descendants:
                descendant_name = NameNormalizer.normalize(
                    getattr(descendant, "name", "") or ""
                )

                part = self.date_part_type_from_name(descendant_name)

                if part:
                    parts_found.add(part)

            if {"YEAR", "MONTH", "DAY"}.issubset(parts_found):
                result.add(field_name)

                for descendant in descendants:
                    descendant_name = NameNormalizer.normalize(
                        getattr(descendant, "name", "") or ""
                    )

                    if self.date_part_type_from_name(descendant_name):
                        result.add(descendant_name)

        return result

    def date_part_type_from_name(self, field_name: str) -> str | None:
        parsed = DateFieldConsolidator.parse_date_part(field_name=field_name)

        if parsed is None:
            return None

        return parsed.get("part")

    def find_field_for_primary_key(self, record, primary_key: str):
        fields = []
        fields.extend(getattr(record, "fields", []) or [])
        fields.extend(getattr(record, "mapping_fields", []) or [])

        normalized_primary_key = NameNormalizer.normalize(primary_key)
        suffix_removed_primary_key = self.remove_record_suffix(normalized_primary_key)

        for field in fields:
            field_name = NameNormalizer.normalize(getattr(field, "name", "") or "")

            if field_name == normalized_primary_key:
                return field

            if self.remove_record_suffix(field_name) == suffix_removed_primary_key:
                return field

        return None

    def datatype_for_key_field(self, key_field) -> str:
        datatype = getattr(key_field, "datatype", None)

        if datatype:
            return datatype

        picture = str(getattr(key_field, "picture", "") or "").upper()

        if "X" in picture:
            return "CHAR"

        if "9" in picture:
            return "DECIMAL"

        return "CHAR"

    def length_for_key_field(self, key_field) -> int | None:
        length = getattr(key_field, "length", None)

        if length:
            try:
                return int(length)
            except Exception:
                pass

        return 20

    def adjust_occurs_field(self, field):
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
            return field.model_copy(update={"length": adjusted_length})
        except Exception:
            try:
                field.length = adjusted_length
            except Exception:
                pass

            return field

    def is_non_physical_group_field(self, field) -> bool:
        if self.is_date_field(field):
            return False

        if getattr(field, "is_group", False):
            return True

        if getattr(field, "has_child", False):
            return True

        return False

    def has_physical_definition(self, field) -> bool:
        if getattr(field, "picture", None):
            return True

        if getattr(field, "datatype", None):
            return True

        if getattr(field, "length", None):
            return True

        return False

    def is_date_field(self, field) -> bool:
        datatype = str(getattr(field, "datatype", "") or "").upper()
        basetype = str(getattr(field, "basetype", "") or "").upper()

        field_name = NameNormalizer.normalize(getattr(field, "name", "") or "")
        normalized_name = field_name.replace(" ", "_")

        return (
            datatype == "DATE"
            or basetype == "DATE"
            or normalized_name.endswith("_DATE")
            or normalized_name == "DATE"
            or "_DATE_" in normalized_name
        )

    def is_filler_field(self, field) -> bool:
        return str(getattr(field, "name", "") or "").upper().startswith("FILLER")

    def is_date_part_name(self, field_name: str) -> bool:
        return DateFieldConsolidator.parse_date_part(field_name=field_name) is not None

    def remove_record_suffix(self, field_name: str) -> str:
        normalized = NameNormalizer.normalize(field_name)
        normalized = normalized.replace(" ", "_")

        return re.sub(r"_[0-9]{4}$", "", normalized)

    def add_sets_and_relationships(self, schema: CanonicalSchema, metadata) -> None:
        added_relationships = set()

        for rel in getattr(metadata, "relationships", []) or []:
            set_name = getattr(rel, "set_name", None)
            owner_record = getattr(rel, "owner_record", None)
            member_record = getattr(rel, "member_record", None)

            if not set_name or not owner_record or not member_record:
                continue

            normalized_set_name = NameNormalizer.normalize(set_name)
            normalized_owner = NameNormalizer.normalize(owner_record)
            normalized_member = NameNormalizer.normalize(member_record)

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