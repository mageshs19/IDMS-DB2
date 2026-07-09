from idms_modernizer.domain.canonical_models import (
    CanonicalSchema,
    CanonicalRecord,
    CanonicalField,
    CanonicalSet,
    CanonicalRelationship
)

from idms_modernizer.services.name_normalizer import (
    NameNormalizer
)

from idms_modernizer.services.date_field_consolidator import (
    DateFieldConsolidator
)


class CanonicalSchemaBuilder:

    def build(
        self,
        metadata
    ) -> CanonicalSchema:

        schema = CanonicalSchema()

        #
        # Records
        #
        for record in metadata.records:

            print(
                f"CanonicalBuilder Input: "
                f"{record.name} "
                f"PK={record.primary_key}"
            )

            canonical_record = CanonicalRecord(
                name=NameNormalizer.normalize(
                    record.name
                ),
                primary_key=(
                    NameNormalizer.normalize(
                        record.primary_key
                    )
                    if record.primary_key
                    else None
                )
            )

            print(
                f"CanonicalRecord Created: "
                f"{canonical_record.name} "
                f"PK={canonical_record.primary_key}"
            )
            normalized_fields = (
                DateFieldConsolidator.consolidate(
                    record.fields
                )
            )

            added_fields = set()

            for field in normalized_fields:

                field_name = (
                    NameNormalizer.normalize(
                        field.name
                    )
                )

                if field_name in added_fields:
                    continue

                added_fields.add(
                    field_name
                )

                canonical_record.fields.append(
                    CanonicalField(
                        name=field_name,
                        datatype=field.datatype,
                        length=field.length,
                        scale=field.scale
                    )
                )

            schema.records.append(
                canonical_record
            )

        #
        # Sets
        #
        added_relationships = set()
        for rel in metadata.relationships:

            key = (
                rel.owner_record,
                rel.member_record,
                rel.set_name
            )

            if key in added_relationships:
                continue

            added_relationships.add(
                key
            )

            schema.sets.append(
                CanonicalSet(
                    name=rel.set_name,
                    owner_record=NameNormalizer.normalize(
                        rel.owner_record
                    ),
                    member_record=NameNormalizer.normalize(
                        rel.member_record
                    )
                )
            )

            schema.relationships.append(
                CanonicalRelationship(
                    set_name=rel.set_name,
                    parent_record=NameNormalizer.normalize(
                        rel.owner_record
                    ),
                    child_record=NameNormalizer.normalize(
                        rel.member_record
                    ),
                    cardinality="1:N"
                )
            )
        return schema