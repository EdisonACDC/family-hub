"""A tablet that connects while Home Assistant is still down, and the names of the calendars.

The add-on can start before Home Assistant. A browser then has no identity yet ("pending"), and
must become the right person as soon as Home Assistant answers, without reloading the page."""

from __future__ import annotations

import asyncio
from typing import Any

from app.ha_link import HAError
from app.server import Hub

MAMMA = {"id": "mamma", "name": "Mamma", "role": "adult", "ha_user_id": "u-mamma"}


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, message: dict[str, Any]) -> None:
        self.sent.append(message)


class StubHA:
    """Just what the hub reads: the states, the users, and the connection flag."""

    def __init__(self) -> None:
        self.connected = False
        self.on_connection: Any = None
        self.states: list[dict[str, Any]] = []
        self.users: list[dict[str, Any]] = []

    async def call(self, kind: str, **kwargs: Any) -> Any:
        if not self.connected:
            raise HAError("not connected to Home Assistant")
        if kind == "get_states":
            return list(self.states)
        if kind == "config/auth/list":
            return list(self.users)
        if kind == "family_hub/ics/list":
            return {"calendars": []}
        return {}

    async def subscribe(self, kind: str, handler: Any, **kwargs: Any) -> int:
        return 1

    async def unsubscribe(self, sub: int) -> None:
        return None


def _ha_with_family() -> StubHA:
    ha = StubHA()
    ha.states = [
        {
            "entity_id": "calendar.family_hub_famiglia",
            "state": "off",
            "attributes": {
                "friendly_name": "Family Hub Famiglia",
                "category_id": "famiglia",
                "category_name": "Famiglia",
                "persons": [MAMMA],
                "shared_users": [],
            },
        }
    ]
    ha.users = [{"id": "u-mamma", "name": "Mamma", "group_ids": []}]
    return ha


def _run(coro: Any) -> None:
    asyncio.run(coro)


def test_a_browser_that_connected_while_home_assistant_was_down_becomes_the_person() -> None:
    async def scenario() -> None:
        ha = _ha_with_family()
        hub = Hub(ha)  # type: ignore[arg-type]
        ws = FakeSocket()
        hub.browsers[ws] = "u-mamma"  # type: ignore[index]

        await hub.send_identity(ws, "u-mamma")  # type: ignore[arg-type]
        assert ws.sent[-1]["role"] == "pending"

        # Home Assistant answers: the same browser is told again, without a reload.
        ha.connected = True
        await hub.on_ha_connection(True)
        identity = [m for m in ws.sent if m.get("type") == "identity"][-1]
        assert identity["role"] == "adult"
        assert identity["person_id"] == "mamma"
        assert identity["user_name"] == "Mamma"

        # And when Home Assistant drops, it is pending again, not a guest.
        ha.connected = False
        await hub.on_ha_connection(False)
        assert ws.sent[-1]["role"] == "pending"

    _run(scenario())


def test_a_guest_stays_a_guest_once_home_assistant_answers() -> None:
    async def scenario() -> None:
        ha = _ha_with_family()
        ha.connected = True
        hub = Hub(ha)  # type: ignore[arg-type]
        ws = FakeSocket()
        hub.browsers[ws] = "u-estraneo"  # type: ignore[index]
        await hub.send_identity(ws, "u-estraneo")  # type: ignore[arg-type]
        assert ws.sent[-1]["role"] == "guest"

    _run(scenario())


def test_the_calendar_shows_the_family_category_name_not_the_friendly_name() -> None:
    async def scenario() -> None:
        ha = _ha_with_family()
        ha.connected = True
        hub = Hub(ha)  # type: ignore[arg-type]
        (calendar,) = await hub.family_calendars()
        assert calendar["name"] == "Famiglia"

        # Without the category name (an older integration), the friendly name is used.
        del ha.states[0]["attributes"]["category_name"]
        (calendar,) = await hub.family_calendars()
        assert calendar["name"] == "Family Hub Famiglia"

    _run(scenario())
