"""0.10.2: an administrator of Home Assistant (or its owner) always has an adult's permissions in
Family Hub: the full menu and Condivisione, the guide and the external calendars. Whether it is
linked to a person or not, and whatever role that person has. Everyone else is as before."""

from __future__ import annotations

import asyncio
from typing import Any

from app.server import Hub

from tests.test_identity_reconnect import MAMMA, FakeSocket, _ha_with_family


def _identity(
    users: list[dict[str, Any]], persons: list[dict[str, Any]], user: str
) -> dict[str, Any]:
    async def scenario() -> dict[str, Any]:
        ha = _ha_with_family()
        ha.connected = True
        ha.users = users
        ha.states[0]["attributes"]["persons"] = persons
        hub = Hub(ha)  # type: ignore[arg-type]
        ws = FakeSocket()
        await hub.send_identity(ws, user)  # type: ignore[arg-type]
        return [m for m in ws.sent if m.get("type") == "identity"][-1]

    return asyncio.run(scenario())


ADMIN = {"id": "u-admin", "name": "Admin", "group_ids": ["system-admin"]}
OWNER = {"id": "u-owner", "name": "Titolare", "group_ids": ["system-users"], "is_owner": True}
USER = {"id": "u-user", "name": "Utente", "group_ids": ["system-users"]}


def test_an_admin_not_linked_to_a_person_is_an_adult() -> None:
    assert _identity([ADMIN], [MAMMA], "u-admin")["role"] == "adult"


def test_the_owner_is_an_adult() -> None:
    assert _identity([OWNER], [MAMMA], "u-owner")["role"] == "adult"


def test_an_admin_linked_to_a_guest_or_a_child_person_is_still_an_adult() -> None:
    for role in ("guest", "child"):
        persons = [MAMMA, {"id": "p", "name": "Persona", "role": role, "ha_user_id": "u-admin"}]
        answer = _identity([ADMIN], persons, "u-admin")
        assert answer["role"] == "adult", role
        assert answer["person_id"] == "p"


def test_a_user_who_is_not_an_admin_keeps_the_role_of_the_person() -> None:
    persons = [MAMMA, {"id": "p", "name": "Persona", "role": "child", "ha_user_id": "u-user"}]
    assert _identity([USER], persons, "u-user")["role"] == "child"
    assert _identity([USER], [MAMMA], "u-user")["role"] == "guest"
    assert _identity([USER], [MAMMA], "u-sconosciuto")["role"] == "guest"
