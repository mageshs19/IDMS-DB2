from collections import defaultdict

from idms_modernizer.domain.relationship_models import (
    Relationship,
)


class RelationshipResolver:
    """
    Resolves IDMS SET owner/member relationships from record set memberships.

    Generic behavior only:
    - No hardcoded SET names.
    - No hardcoded record names.
    - OWNER and MEMBER are read from schema listing memberships.
    """

    def resolve(
        self,
        metadata,
    ) -> list[Relationship]:
        owner_map: dict[str, list[str]] = defaultdict(list)
        member_map: dict[str, list[str]] = defaultdict(list)

        for record in getattr(metadata, "records", []) or []:
            record_name = getattr(record, "name", "") or ""

            if not record_name:
                continue

            for membership in getattr(record, "set_memberships", []) or []:
                set_name = (
                    getattr(membership, "set_name", None)
                    or getattr(membership, "name", None)
                    or ""
                )

                role = (
                    getattr(membership, "role", None)
                    or getattr(membership, "relation_type", None)
                    or getattr(membership, "type", None)
                    or ""
                )

                set_name = str(set_name or "").strip().upper()
                role = str(role or "").strip().upper()

                if not set_name:
                    continue

                if not role:
                    continue

                if set_name == "CALC":
                    continue

                if role == "OWNER":
                    if record_name not in owner_map[set_name]:
                        owner_map[set_name].append(record_name)

                elif role == "MEMBER":
                    if record_name not in member_map[set_name]:
                        member_map[set_name].append(record_name)

        relationships: list[Relationship] = []

        all_sets = set(owner_map.keys()) | set(member_map.keys())

        for set_name in sorted(all_sets):
            owners = owner_map.get(set_name, [])
            members = member_map.get(set_name, [])

            if not owners:
                continue

            if not members:
                continue

            for owner in owners:
                for member in members:
                    if not owner or not member:
                        continue

                    if owner == member:
                        continue

                    relationships.append(
                        Relationship(
                            set_name=set_name,
                            owner_record=owner,
                            member_record=member,
                            cardinality="1:N",
                        )
                    )

        metadata.relationships = relationships

        return relationships