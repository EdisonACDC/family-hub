"""The week never goes empty because of one calendar: a Home Assistant calendar marked as rubbish
gets the rubbish colours, and a calendar that cannot be read leaves the others shown."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

from app.ha_link import HAError
from app.server import Hub

from tests.fake_ha import FAMILY, WASTE, FakeHA, stored_event
from tests.helpers import ADULT_USER, connect, request, shutdown, started


def _run(scenario: Any) -> None:
    asyncio.run(scenario())


def test_a_home_assistant_rubbish_calendar_does_not_empty_the_week() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        today = date.today()
        fake.config["sources"]["calendar_styles"] = {
            WASTE: {"name": "Rifiuti", "type": "rifiuti", "color": "#64748B"}
        }
        fake.events[WASTE] = [
            stored_event("Abfuhr: Bioabfall", today.isoformat(), (today + timedelta(1)).isoformat())
        ]
        fake.events[FAMILY].append(
            stored_event("Visita", f"{today} 10:00:00", f"{today} 11:00:00", "mamma")
        )
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, ADULT_USER)
            reply = await request(
                ws,
                {
                    "id": 1,
                    "op": "events",
                    "start": f"{today} 00:00:00",
                    "end": f"{today + timedelta(7)} 00:00:00",
                },
            )
            assert reply["ok"] is True, reply
            events = reply["result"]
            assert [e["summary"] for e in events[FAMILY]] == ["Visita"]
            (pickup,) = events[WASTE]
            assert pickup["waste"] == "bio"
            assert pickup["waste_color"].startswith("#")
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_one_calendar_that_fails_leaves_the_others() -> None:
    async def scenario() -> None:
        hub = Hub.__new__(Hub)

        async def calendars() -> list[dict[str, Any]]:
            return [
                {"entity_id": "calendar.rotto", "external": True, "type": "altro", "color": "#000"},
                {"entity_id": "calendar.buono", "external": True, "type": "altro", "color": "#000"},
            ]

        async def events_of(entity_id: str, start: str, end: str) -> list[dict[str, Any]]:
            if entity_id == "calendar.rotto":
                raise HAError("broken")
            return [{"summary": "Festa", "start": "2026-11-10", "end": "2026-11-11"}]

        hub.calendars = calendars  # type: ignore[method-assign]
        hub._events_of = events_of  # type: ignore[method-assign]
        result = await hub.events("2026-11-09", "2026-11-16", None)  # type: ignore[arg-type]
        assert result["calendar.rotto"] == []
        assert [e["summary"] for e in result["calendar.buono"]] == ["Festa"]

    _run(scenario)
