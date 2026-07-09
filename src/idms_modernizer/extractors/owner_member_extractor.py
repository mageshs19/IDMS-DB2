import re

from idms_modernizer.domain.relationship_models import (
    SetMembership
)


class OwnerMemberExtractor:

    SAME_LINE_PATTERN = re.compile(
        r"^\s*([A-Z0-9\-]+)\s+(?:INDEX\s+)?(OWNER|MEMBER)\b",
        re.IGNORECASE
    )

    SET_NAME_PATTERN = re.compile(
        r"^\s*([A-Z][A-Z0-9\-]+)\s*$",
        re.IGNORECASE
    )

    ROLE_PATTERN = re.compile(
        r"^\s*(OWNER|MEMBER)\b",
        re.IGNORECASE
    )

    IGNORED_SET_NAMES = {
        "CALC"
    }

    HEADER_WORDS = {
        "SET",
        "TYPE",
        "NEXT",
        "PRIOR",
        "OWNER",
        "MEMBER"
    }

    def extract(
        self,
        record_name: str,
        lines: list[str]
    ) -> list[SetMembership]:

        memberships = []
        seen = set()

        in_dbkey_block = False
        pending_set_name = None

        for raw_line in lines:

            line = raw_line.strip().upper()

            if not line:
                continue

            if "DBKEY POSITIONS" in line:
                in_dbkey_block = True
                pending_set_name = None
                continue

            if in_dbkey_block and line.startswith("DATA ITEM"):
                break

            if not in_dbkey_block:
                continue

            same_line_match = self.SAME_LINE_PATTERN.search(
                line
            )

            if same_line_match:

                set_name = same_line_match.group(1).upper()
                role = same_line_match.group(2).upper()

                pending_set_name = None

                if set_name in self.IGNORED_SET_NAMES:
                    continue

                key = (
                    set_name,
                    role
                )

                if key not in seen:
                    seen.add(key)

                    memberships.append(
                        SetMembership(
                            set_name=set_name,
                            role=role
                        )
                    )

                continue

            role_match = self.ROLE_PATTERN.search(
                line
            )

            if role_match and pending_set_name:

                set_name = pending_set_name
                role = role_match.group(1).upper()

                pending_set_name = None

                if set_name in self.IGNORED_SET_NAMES:
                    continue

                key = (
                    set_name,
                    role
                )

                if key not in seen:
                    seen.add(key)

                    memberships.append(
                        SetMembership(
                            set_name=set_name,
                            role=role
                        )
                    )

                continue

            set_name_match = self.SET_NAME_PATTERN.search(
                line
            )

            if set_name_match:

                candidate = set_name_match.group(1).upper()

                if candidate in self.HEADER_WORDS:
                    continue

                if candidate in self.IGNORED_SET_NAMES:
                    pending_set_name = None
                    continue

                pending_set_name = candidate

        print(
            f"{record_name}: "
            f"{len(memberships)} memberships"
        )

        for membership in memberships:
            print(
                f"{record_name} -> "
                f"{membership.set_name} "
                f"{membership.role}"
            )

        return memberships