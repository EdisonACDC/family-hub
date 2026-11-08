"""The add-on server relays between browsers and Home Assistant, and allows only a few actions."""

from __future__ import annotations

import asyncio
from typing import Any

from app.ha_link import HAClient

from tests.fake_ha import FAMILY, SCHOOL, SHOP, WASTE, WEATHER, FakeHA
from tests.helpers import ADULT_USER, connect, request, shutdown, started


def _run(scenario: object) -> None:
    asyncio.run(scenario())  # type: ignore[operator]


def test_connects_and_subscribes_only_to_what_it_needs() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, ha = await started(fake)
        try:
            assert ha.connected
            kinds = sorted(kind for _, kind, _ in fake._subs.values())
            assert kinds == ["entities", "events", "events"]
            # Entity subscription covers the family calendars and nothing else.
            (entity_filter,) = [f for _, k, f in fake._subs.values() if k == "entities"]
            # Family calendars plus the external sources the guide chose, and nothing else.
            assert entity_filter == sorted([FAMILY, SCHOOL, WASTE, SHOP, WEATHER])
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_wrong_token_is_refused_and_not_connected() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, ha = await started(fake, token="wrong")
        try:
            await asyncio.sleep(0.2)
            assert not ha.connected
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_calendars_list_only_family_hub_calendars_with_category_ids() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, ADULT_USER)
            reply = await request(ws, {"id": 1, "op": "calendars"})
            assert reply["ok"] is True
            family = [c["entity_id"] for c in reply["result"] if not c["external"]]
            assert family == [FAMILY, SCHOOL]
            assert reply["result"][1]["category_id"] == "scuola"
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_events_are_read_for_the_requested_window() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        await fake.add_event(
            FAMILY, "Dentista", "2026-11-10T15:00:00+01:00", "2026-11-10T16:00:00+01:00", "mamma"
        )
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, ADULT_USER)
            reply = await request(
                ws,
                {
                    "id": 2,
                    "op": "events",
                    "start": "2026-11-09 00:00:00",
                    "end": "2026-11-16 00:00:00",
                },
            )
            assert reply["ok"] is True
            (event,) = reply["result"][FAMILY]
            assert event["summary"] == "Dentista"
            assert event["person_ids"] == ["mamma"]
            assert reply["result"][SCHOOL] == []
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_allowed_action_is_forwarded_to_home_assistant() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, ADULT_USER)
            reply = await request(
                ws,
                {
                    "id": 3,
                    "op": "service",
                    "service": "add_event",
                    "data": {
                        "category": "scuola",
                        "summary": "Gita",
                        "start": "2026-11-20 09:00:00",
                    },
                },
            )
            assert reply["ok"] is True
            (call,) = [c for c in fake.calls if c["service"] == "add_event"]
            assert call["domain"] == "family_hub"
            assert call["data"]["category"] == "scuola"
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_other_services_are_refused() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, ADULT_USER)
            reply = await request(ws, {"id": 4, "op": "service", "service": "reload", "data": {}})
            assert reply["ok"] is False
            other = await request(
                ws,
                {"id": 5, "op": "service", "service": "lock", "data": {"entity_id": "lock.door"}},
            )
            assert other["ok"] is False
            assert fake.calls == []
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_reminder_events_reach_adult_browsers() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, ADULT_USER)
            data = {"uid": "u1", "title": "Promemoria", "message": "15:00 · Dentista"}
            await fake.push_event("family_hub_reminder", data)
            msg = await ws.receive_json(timeout=5)
            assert msg == {"type": "event", "event_type": "family_hub_reminder", "data": data}
            await fake.push_event("family_hub_reminder_closed", {"uid": "u1"})
            closed = await ws.receive_json(timeout=5)
            assert closed["event_type"] == "family_hub_reminder_closed"
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_only_family_hub_calendar_changes_are_forwarded() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, ADULT_USER)
            await fake.push_entity_change("light.kitchen")
            await fake.push_entity_change(SCHOOL)
            msg = await ws.receive_json(timeout=5)
            assert msg == {"type": "state_changed", "entity_id": SCHOOL}
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


async def _next_of_type(ws: Any, kind: str, seconds: float) -> dict[str, Any]:
    """The next message of one type (identity messages may come first)."""
    while True:
        msg = await ws.receive_json(timeout=seconds)
        if msg.get("type") == kind:
            return dict(msg)


def test_server_reports_when_home_assistant_drops_and_comes_back() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, ha = await started(fake)
        try:
            ws = await connect(client, ADULT_USER)
            await fake.drop_connections()
            # Each change is followed by the browser's identity again: skip those.
            down = await _next_of_type(ws, "connection", 5)
            assert down == {"type": "connection", "connected": False}
            up = await _next_of_type(ws, "connection", 10)
            assert up == {"type": "connection", "connected": True}
            assert isinstance(ha, HAClient) and ha.connected
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)
