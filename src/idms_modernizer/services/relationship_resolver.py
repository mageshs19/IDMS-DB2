from collections import defaultdict

from idms_modernizer.domain.relationship_models import (
    Relationship
)


class RelationshipResolver:

    def resolve(
        self,
        metadata
    ) -> list[Relationship]:

        owner_map = defaultdict(list)

        member_map = defaultdict(list)

        for record in metadata.records:

            for membership in record.set_memberships:

                if membership.role == "OWNER":

                    owner_map[
                        membership.set_name
                    ].append(
                        record.name
                    )

                elif membership.role == "MEMBER":

                    member_map[
                        membership.set_name
                    ].append(
                        record.name
                    )

        relationships = []

        all_sets = (
            set(owner_map.keys())
            | set(member_map.keys())
        )

        for set_name in all_sets:

            owners = owner_map.get(
                set_name,
                []
            )

            members = member_map.get(
                set_name,
                []
            )

            for owner in owners:

                for member in members:

                    relationships.append(
                        Relationship(
                            set_name=set_name,
                            owner_record=owner,
                            member_record=member
                        )
                    )

        return relationships