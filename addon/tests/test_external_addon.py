"""External calendars in the add-on: only adults add, change or remove them, the link is shown
to adults only, the calendar is read only and shown to everyone, and files are size-checked."""

from __future__ import annotations

import asyncio
from typing import Any

from tests.fake_ha import FakeHA
from tests.helpers import ADULT_USER, CHILD_USER, GUEST_USER, connect, request, shutdown, started

ICS = "BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n"
LINK = "https://example.org/rest.ics"


def _run(scenario: Any) -> None:
    asyncio.run(scenario())


def test_adult_adds_a_link_and_the_calendar_is_read_only_for_everyone() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            adult = await connect(client, ADULT_USER)
            reply = await request(
                adult,
                {
                    "id": 1,
                    "op": "ics_add",
                    "url": LINK,
                    "calendar": {"name": "Rifiuti", "type": "rifiuti", "persons": ["mamma"]},
                },
            )
            assert reply["ok"] is True, reply
            source_id = reply["result"]["id"]
            listed = await request(adult, {"id": 2, "op": "ics_list"})
            (entry,) = listed["result"]["calendars"]
            assert entry["url"] == LINK  # adults see the link
            await adult.close()
            # Everyone sees the calendar's events, and nobody can change it from here.
            guest = await connect(client, GUEST_USER)
            events = await request(
                guest, {"id": 3, "op": "events", "start": "2026-11-01", "end": "2026-12-01"}
            )
            key = f"calendar.family_hub_ext_{source_id}"
            assert key in events["result"]
            assert events["result"][key][0]["external"] is True
            await guest.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_children_and_guests_cannot_add_change_or_remove() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            for user in (CHILD_USER, GUEST_USER):
                ws = await connect(client, user)
                add = await request(
                    ws,
                    {
                        "id": 1,
                        "op": "ics_add",
                        "url": LINK,
                        "calendar": {"name": "X", "type": "altro", "persons": []},
                    },
                )
                assert add["error"] == "forbidden"
                assert (await request(ws, {"id": 2, "op": "ics_list"}))["error"] == "forbidden"
                await ws.close()
            assert fake.ics == {}
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_a_file_too_big_is_refused_before_it_is_sent() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            adult = await connect(client, ADULT_USER)
            huge = ICS + "X-PAD:" + "a" * (6 * 1024 * 1024)
            reply = await request(
                adult,
                {
                    "id": 1,
                    "op": "ics_add",
                    "content": huge,
                    "calendar": {"name": "Ferien", "type": "vacanze_scuola", "persons": []},
                },
            )
            assert reply["error"] == "too_large"
            assert fake.ics == {}
            await adult.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_an_invalid_file_is_refused_and_nothing_is_kept() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            adult = await connect(client, ADULT_USER)
            reply = await request(
                adult,
                {
                    "id": 1,
                    "op": "ics_add",
                    "content": "not a calendar",
                    "calendar": {"name": "Ferien", "type": "vacanze_scuola", "persons": []},
                },
            )
            assert reply["error"] == "invalid_ics"
            assert fake.ics == {}
            await adult.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_adult_replaces_removes_and_refreshes() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            adult = await connect(client, ADULT_USER)
            added = await request(
                adult,
                {
                    "id": 1,
                    "op": "ics_add",
                    "content": ICS,
                    "calendar": {"name": "Ferien", "type": "vacanze_scuola", "persons": []},
                },
            )
            source_id = added["result"]["id"]
            replaced = await request(
                adult, {"id": 2, "op": "ics_replace", "calendar_id": source_id, "content": ICS}
            )
            assert replaced["ok"] is True, replaced
            removed = await request(adult, {"id": 3, "op": "ics_remove", "calendar_id": source_id})
            assert removed["ok"] is True
            assert fake.ics == {}
            await adult.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_rubbish_pickups_carry_their_kind_and_colour() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            adult = await connect(client, ADULT_USER)
            added = await request(
                adult,
                {
                    "id": 1,
                    "op": "ics_add",
                    "content": ICS,
                    "calendar": {
                        "name": "Abfuhr",
                        "type": "rifiuti",
                        "color": "#111111",
                        "persons": [],
                    },
                },
            )
            source_id = added["result"]["id"]
            key = f"calendar.family_hub_ext_{source_id}"
            fake.events[key] = [
                {
                    "summary": "Restmüll, Biotonne",
                    "start": "2026-11-09",
                    "end": "2026-11-10",
                    "location": "",
                    "record_id": "",
                    "shift_id": "",
                    "person_ids": "",
                },
            ]
            await adult.close()
            guest = await connect(client, GUEST_USER)
            events = await request(
                guest, {"id": 2, "op": "events", "start": "2026-11-01", "end": "2026-12-01"}
            )
            item = events["result"][key][0]
            assert item["waste"] == "restmuell"
            assert item["waste_label"] == "Indifferenziato"
            assert item["waste_icon"] == "mdi:trash-can-outline"
            assert item["waste_color"] == "#9E9E9E"
            await guest.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_only_adults_change_the_rubbish_colours() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            child = await connect(client, CHILD_USER)
            denied = await request(
                child, {"id": 1, "op": "ics_styles", "styles": {"bio": "#00ff00"}}
            )
            assert denied["error"] == "forbidden"
            await child.close()
            adult = await connect(client, ADULT_USER)
            saved = await request(
                adult, {"id": 2, "op": "ics_styles", "styles": {"bio": "#00ff00"}}
            )
            assert saved["ok"] is True
            assert fake.waste_styles["bio"] == "#00ff00"
            await adult.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)
