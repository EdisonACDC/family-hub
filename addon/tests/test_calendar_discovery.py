"""0.7.5: the calendars are found in the entity registry, never by their entity id. An area in front
of the id (calendar.ingresso_casa_family_hub_famiglia), a name given by hand (calendar.agenda_casa),
an ICS calendar renamed by hand, and a calendar only named like one of Family Hub's are all handled
right."""

from __future__ import annotations

import asyncio
from typing import Any

from tests.fake_ha import FAMILY, FakeHA, stored_event
from tests.helpers import ADULT_USER, connect, request, shutdown, started


def _run(scenario: Any) -> None:
    asyncio.run(scenario())


def _ids(calendars: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {c["entity_id"]: c for c in calendars}


def test_a_family_calendar_under_an_area_is_found_and_works() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            new_id = "calendar.ingresso_casa_family_hub_famiglia"
            fake.rename_calendar(FAMILY, new_id)
            fake.events[new_id].append(
                stored_event("Visita", "2026-11-10T09:00:00", "2026-11-10T10:00:00")
            )
            ws = await connect(client, ADULT_USER)
            reply = await request(ws, {"id": 1, "op": "calendars"})
            found = _ids(reply["result"])
            assert new_id in found
            assert found[new_id]["external"] is False
            events = await request(
                ws,
                {
                    "id": 2,
                    "op": "events",
                    "start": "2026-11-10T00:00:00+01:00",
                    "end": "2026-11-11T00:00:00+01:00",
                },
            )
            assert [e["summary"] for e in events["result"][new_id]] == ["Visita"], events
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_a_calendar_renamed_by_hand_works_the_same() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            fake.rename_calendar(FAMILY, "calendar.agenda_casa")
            ws = await connect(client, ADULT_USER)
            found = _ids((await request(ws, {"id": 1, "op": "calendars"}))["result"])
            assert "calendar.agenda_casa" in found
            assert found["calendar.agenda_casa"]["name"] == "Famiglia"
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_an_ics_calendar_renamed_by_hand_is_a_read_only_calendar() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            fake.ics["abc12345"] = {
                "name": "Scuola ICS",
                "type": "altro",
                "color": "#111111",
                "persons": [],
                "url": "",
                "content": "",
            }
            fake.states.append(
                {
                    "entity_id": "calendar.agenda_scuola",
                    "state": "off",
                    "attributes": {"friendly_name": "Scuola ICS", "source_id": "abc12345"},
                }
            )
            ws = await connect(client, ADULT_USER)
            found = _ids((await request(ws, {"id": 1, "op": "calendars"}))["result"])
            assert found["calendar.agenda_scuola"]["external"] is True
            assert found["calendar.agenda_scuola"]["name"] == "Scuola ICS"
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_a_calendar_only_named_like_one_of_ours_is_not_taken() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            # Named like Family Hub's, but not made by it: not in the entity registry.
            fake.states.append(
                {"entity_id": "calendar.family_hub_impostore", "state": "off", "attributes": {}}
            )
            ws = await connect(client, ADULT_USER)
            found = _ids((await request(ws, {"id": 1, "op": "calendars"}))["result"])
            assert "calendar.family_hub_impostore" not in found
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)
