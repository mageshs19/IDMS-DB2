class ValidationService:

    def validate_metadata(
        self,
        metadata
    ) -> list[str]:

        errors = []

        record_names = {
            record.name
            for record in metadata.records
        }

        for rel in metadata.relationships:

            if rel.owner_record not in record_names:

                errors.append(
                    f"Missing Owner Record: {rel.owner_record}"
                )

            if rel.member_record not in record_names:

                errors.append(
                    f"Missing Member Record: {rel.member_record}"
                )

        return errors