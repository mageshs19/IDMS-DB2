from idms_modernizer.domain.canonical_models import (
    CanonicalSchema,
    CanonicalField
)
from idms_modernizer.domain.schema_models import SchemaMetadata
from idms_modernizer.services.name_normalizer import NameNormalizer


class CanonicalReconciler:
    """
    Reconciles canonical schema with IDMS schema metadata.

    IDMS schema is authoritative for:
    - datatype
    - length
    - scale
    - picture

    Canonical schema is authoritative for:
    - normalized record names
    - primary keys
    - relationships
    """

    def reconcile(
        self,
        canonical_schema: CanonicalSchema,
        metadata: SchemaMetadata
    ) -> CanonicalSchema:

        idms_field_lookup = self._build_idms_field_lookup(
            metadata
        )

        for record in canonical_schema.records:
            normalized_record_name = NameNormalizer.normalize(
                record.name
            )

            reconciled_fields: list[CanonicalField] = []

            for field in record.fields:
                normalized_field_name = NameNormalizer.normalize(
                    field.name
                )

                idms_field = idms_field_lookup.get(
                    (
                        normalized_record_name,
                        normalized_field_name
                    )
                )

                if idms_field is None:
                    idms_field = idms_field_lookup.get(
                        (
                            normalized_record_name,
                            self._remove_record_suffix(
                                normalized_field_name
                            )
                        )
                    )

                if idms_field is None:
                    reconciled_fields.append(field)
                    continue

                reconciled_fields.append(
                    CanonicalField(
                        name=field.name,
                        datatype=idms_field.datatype,
                        length=idms_field.length,
                        scale=idms_field.scale,
                        occurs=field.occurs,
                        occurs_max=field.occurs_max
                    )
                )

            record.fields = reconciled_fields

        return canonical_schema

    def _build_idms_field_lookup(
        self,
        metadata: SchemaMetadata
    ) -> dict[tuple[str, str], object]:

        lookup: dict[tuple[str, str], object] = {}

        for record in metadata.records:
            record_name = NameNormalizer.normalize(
                record.name
            )

            for field in record.fields:
                field_name = NameNormalizer.normalize(
                    field.name
                )

                lookup[
                    (
                        record_name,
                        field_name
                    )
                ] = field

                lookup[
                    (
                        record_name,
                        self._remove_record_suffix(field_name)
                    )
                ] = field

        return lookup

    def _remove_record_suffix(
        self,
        field_name: str
    ) -> str:

        parts = field_name.split("_")

        if (
            len(parts) > 1
            and parts[-1].isdigit()
            and len(parts[-1]) == 4
        ):
            return "_".join(parts[:-1])

        return field_name