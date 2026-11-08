"""Who may do what: roles from the family's persons, matched by Home Assistant user.

- adult: everything.
- shared: a shared screen (a Home Assistant user not linked to a person, e.g. the kitchen
  tablet). Adds, changes and ticks events and lists like an adult, but does not open the
  settings.
- child: sees, adds and changes only events where the child is one of the persons.
- guest, or any user not linked to a person: read only.

The user comes from the X-Remote-User-Id header that Home Assistant's Ingress adds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ADULT = "adult"
SHARED = "shared"
CHILD = "child"
GUEST = "guest"
ROLES = (ADULT, SHARED, CHILD, GUEST)


@dataclass(frozen=True)
class Identity:
    role: str
    person_id: str | None

    def as_dict(self) -> dict[str, str | None]:
        return {"role": self.role, "person_id": self.person_id}


GUEST_IDENTITY = Identity(GUEST, None)


def identify(
    user_id: str | None,
    persons: list[dict[str, Any]],
    shared_users: list[str] | tuple[str, ...] = (),
) -> Identity:
    """The identity of a request. Unknown users are guests."""
    if not user_id:
        return GUEST_IDENTITY
    for person in persons:
        if person.get("ha_user_id") == user_id:
            role = person.get("role", GUEST)
            if role not in ROLES:
                return GUEST_IDENTITY
            return Identity(role, str(person["id"]))
    if user_id in shared_users:
        return Identity(SHARED, None)
    return GUEST_IDENTITY


def can_write(identity: Identity) -> bool:
    return identity.role in (ADULT, SHARED, CHILD)


def can_see(identity: Identity, person_ids: list[str]) -> bool:
    """Children only see events they take part in."""
    if identity.role in (ADULT, SHARED):
        return True
    if identity.role == CHILD:
        return identity.person_id in person_ids
    return True  # guests read everything


def can_change(identity: Identity, person_ids: list[str]) -> bool:
    """Adults and shared screens change anything; children change only their own events."""
    if identity.role in (ADULT, SHARED):
        return True
    if identity.role == CHILD:
        return identity.person_id in person_ids
    return False
