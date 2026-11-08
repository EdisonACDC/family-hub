"""Importing old calendars: adults only, a preview first, the last 30 days and the future are
copied, and running the import again never duplicates an event."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

from app.importer import key_of, plan, service_data

from tests.fake_ha import FakeHA, stored_event
from tests.helpers import ADULT_USER, CHILD_USER, GUEST_USER, connect, request, shutdown, started

OLD = "calendar.vecchio"


def _at(days: int, time: str = "10:00:00") -> str:
    return f"{date.today() + timedelta(days=days)} {time}"


def _with_old_calendar(fake: FakeHA) -> None:
    fake.states.append(
        {"entity_id": OLD, "state": "off", "attributes": {"friendly_name": "Vecchio"}}
    )
    fake.events[OLD] = [
        stored_event("Dentista", _at(-5), _at(-5, "11:00:00")),  # last 30 days: copied
        stored_event("Festa", _at(10), _at(10, "18:00:00")),  # future: copied
        stored_event("Vacanza", _at(400), _at(400)),  # far ahead: copied
        stored_event("Vecchissimo", _at(-60), _at(-60, "11:00:00")),  # too old: not copied
    ]


def _run(scenario: Any) -> None:
    asyncio.run(scenario())


def test_plan_skips_what_is_already_there_and_repeats() -> None:
    existing = [{"summary": "Festa", "start": "2026-11-10 18:00", "end": "2026-11-10 19:00"}]
    source = [
        {"summary": "Festa", "start": "2026-11-10 18:00", "end": "2026-11-10 19:00"},
        {"summary": "Cena", "start": "2026-11-11 20:00", "end": "2026-11-11 21:00"},
        {"summary": "Cena", "start": "2026-11-11 20:00", "end": "2026-11-11 21:00"},
        {"summary": "", "start": "2026-11-12 09:00", "end": "2026-11-12 10:00"},
    ]
    to_copy, skipped = plan(source, existing)
    assert [e["summary"] for e in to_copy] == ["Cena"]
    assert skipped == 2
    assert key_of(source[0]) == ("Festa", "2026-11-10 18:00", "2026-11-10 19:00")


def test_service_data_keeps_the_person_and_location() -> None:
    event = {"summary": " Visita ", "start": "2026-11-10", "end": "2026-11-11", "location": "Via A"}
    assert service_data(event, "famiglia", ["mamma"]) == {
        "category": "famiglia",
        "summary": "Visita",
        "start": "2026-11-10",
        "end": "2026-11-11",
        "persons": ["mamma"],
        "location": "Via A",
    }


def test_preview_then_import_copies_once() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        _with_old_calendar(fake)
        ha_server, client, _ = await started(fake)
        try:
            adult = await connect(client, ADULT_USER)
            sources = await request(adult, {"id": 1, "op": "import_sources"})
            listed = [s["entity_id"] for s in sources["result"]]
            assert OLD in listed
            assert not any(e.startswith("calendar.family_hub_") for e in listed)
            base = {"entity_id": OLD, "category_id": "famiglia", "person": ""}
            preview = await request(adult, {"id": 2, "op": "import_preview", **base})
            assert preview["result"]["total"] == 3
            assert preview["result"]["skipped"] == 0
            assert [i["summary"] for i in preview["result"]["items"]] == [
                "Dentista",
                "Festa",
                "Vacanza",
            ]
            assert not any(c["service"] == "add_event" for c in fake.calls)

            first = await request(adult, {"id": 3, "op": "import_run", **base})
            assert first["result"] == {"copied": 3, "skipped": 0}
            again = await request(adult, {"id": 4, "op": "import_run", **base})
            assert again["result"] == {"copied": 0, "skipped": 3}

            added = [c for c in fake.calls if c["service"] == "add_event"]
            assert len(added) == 3
            assert added[0]["data"]["category"] == "famiglia"
            titles = [e["summary"] for e in fake.events["calendar.family_hub_famiglia"]]
            assert sorted(titles) == ["Dentista", "Festa", "Vacanza"]
            await adult.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_only_adults_import_and_only_from_old_calendars() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        _with_old_calendar(fake)
        ha_server, client, _ = await started(fake)
        try:
            for user in (CHILD_USER, GUEST_USER):
                ws = await connect(client, user)
                reply = await request(ws, {"id": 1, "op": "import_sources"})
                assert reply["error"] == "forbidden"
                await ws.close()
            adult = await connect(client, ADULT_USER)
            family = "calendar.family_hub_famiglia"
            bad = await request(
                adult,
                {"id": 2, "op": "import_preview", "entity_id": family, "category_id": "famiglia"},
            )
            assert bad["error"] == "bad_request"
            unknown = await request(
                adult,
                {"id": 3, "op": "import_preview", "entity_id": OLD, "category_id": "nessuna"},
            )
            assert unknown["error"] == "not_found"
            assert [c for c in fake.calls if c["service"] == "add_event"] == []
            await adult.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)
