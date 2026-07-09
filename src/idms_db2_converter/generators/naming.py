import re


class Naming:
    @staticmethod
    def normalize(
        value: str | None,
    ) -> str:
        if not value:
            return ""

        normalized = str(value).strip().upper()
        normalized = normalized.replace("_", "-")
        normalized = normalized.replace(" ", "-")
        normalized = re.sub(
            r"[^A-Z0-9-]",
            "-",
            normalized,
        )
        normalized = re.sub(
            r"-+",
            "-",
            normalized,
        )

        return normalized.strip("-")

    @staticmethod
    def hv(
        record: str,
        field: str,
    ) -> str:
        record_name = Naming.normalize(
            record,
        )

        field_name = Naming.normalize(
            field,
        )

        return f"HV-{record_name}-{field_name}"

    @staticmethod
    def ni(
        record: str,
        field: str,
    ) -> str:
        record_name = Naming.normalize(
            record,
        )

        field_name = Naming.normalize(
            field,
        )

        return f"NI-{record_name}-{field_name}"

    @staticmethod
    def cursor(
        set_name: str,
    ) -> str:
        return f"C-{Naming.normalize(set_name)}"