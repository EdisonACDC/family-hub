"""Shifts in the add-on: who reads and changes which person's shifts, the confirmation for
changed times, and putting shifts on days."""

from __future__ import annotations

import asyncio
from typing import Any

from tests.fake_ha import FAMILY, FakeHA
from tests.helpers import ADULT_USER, CHILD_USER, GUEST_USER, connect, request, shutdown, started

Mattina = {
    "id": "mattina",
    "name": "Mattina",
    "start": "06:00",
    "end": "14:00",
    "category": "famiglia",
}
NIGHT = {"id": "nt", "name": "Notte", "start": "22:00", "end": "06:00", "category": "famiglia"}


def _run(scenario: Any) -> None:
    asyncio.run(scenario())


def _fake_with_shifts() -> FakeHA:
    fake = FakeHA()
    fake.config["shifts"] = {"sofia": [dict(Mattina)], "mamma": [dict(NIGHT)]}
    return fake


def test_adult_reads_everyones_shifts_child_only_their_own() -> None:
    async def scenario() -> None:
        fake = _fake_with_shifts()
        ha_server, client, _ = await started(fake)
        try:
            adult = await connect(client, ADULT_USER)
            everyone = await request(adult, {"id": 1, "op": "shifts"})
            assert sorted(everyone["result"]["shifts"]) == ["mamma", "sofia"]
            await adult.close()
            child = await connect(client, CHILD_USER)
            own = await request(child, {"id": 2, "op": "shifts"})
            assert list(own["result"]["shifts"]) == ["sofia"]
            await child.close()
            guest = await connect(client, GUEST_USER)
            assert (await request(guest, {"id": 3, "op": "shifts"}))["ok"] is False
            await guest.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_child_saves_own_shifts_only() -> None:
    async def scenario() -> None:
        fake = _fake_with_shifts()
        ha_server, client, _ = await started(fake)
        try:
            child = await connect(client, CHILD_USER)
            mine = await request(
                child,
                {
                    "id": 1,
                    "op": "shifts_save",
                    "person": "sofia",
                    "shifts": [
                        dict(Mattina),
                        {"name": "Sera", "start": "14:00", "end": "20:00", "category": "famiglia"},
                    ],
                },
            )
            assert mine["ok"] is True, mine
            theirs = await request(
                child, {"id": 2, "op": "shifts_save", "person": "mamma", "shifts": []}
            )
            assert theirs == {"id": 2, "type": "result", "ok": False, "error": "forbidden"}
            assert [s["name"] for s in fake.config["shifts"]["sofia"]] == ["Mattina", "Sera"]
            await child.close()
            guest = await connect(client, GUEST_USER)
            assert (
                await request(
                    guest, {"id": 3, "op": "shifts_save", "person": "sofia", "shifts": []}
                )
            )["error"] == "forbidden"
            await guest.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_changed_times_ask_before_touching_future_events() -> None:
    async def scenario() -> None:
        fake = _fake_with_shifts()
        await fake.add_event(
            FAMILY, "Mattina", "2027-03-03T06:00:00+01:00", "2027-03-03T14:00:00+01:00", "sofia"
        )
        fake.events[FAMILY][-1]["shift_id"] = "mattina"
        ha_server, client, _ = await started(fake)
        try:
            adult = await connect(client, ADULT_USER)
            moved = {**Mattina, "start": "08:00"}
            asked = await request(
                adult, {"id": 1, "op": "shifts_save", "person": "sofia", "shifts": [moved]}
            )
            assert asked == {"id": 1, "type": "result", "ok": True, "result": {"confirm": 1}}
            assert fake.shift_saves == []
            confirmed = await request(
                adult,
                {
                    "id": 2,
                    "op": "shifts_save",
                    "person": "sofia",
                    "shifts": [moved],
                    "apply_future": True,
                },
            )
            assert confirmed["ok"] is True
            assert fake.shift_saves[-1]["apply_future"] is True
            await adult.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_shift_is_put_on_several_days_with_its_times() -> None:
    async def scenario() -> None:
        fake = _fake_with_shifts()
        ha_server, client, _ = await started(fake)
        try:
            child = await connect(client, CHILD_USER)
            reply = await request(
                child,
                {
                    "id": 1,
                    "op": "shifts_apply",
                    "person": "sofia",
                    "shift_id": "mattina",
                    "days": ["2031-04-01", "2031-04-02", "2031-04-03"],
                },
            )
            assert reply["ok"] is True, reply
            assert reply["result"] == {"removed": 0, "inserted": 3}
            adds = [c["data"] for c in fake.calls if c["service"] == "add_event"]
            assert [a["start"] for a in adds] == [
                "2031-04-01 06:00:00",
                "2031-04-02 06:00:00",
                "2031-04-03 06:00:00",
            ]
            assert all(a["end"].endswith("14:00:00") and a["persons"] == ["sofia"] for a in adds)
            assert all(a["summary"] == "Mattina" and a["shift_id"] == "mattina" for a in adds)
            await child.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_changing_and_removing_a_day_replaces_its_shift() -> None:
    async def scenario() -> None:
        fake = _fake_with_shifts()
        await fake.add_event(
            FAMILY, "Mattina", "2031-05-05T06:00:00+01:00", "2031-05-05T14:00:00+01:00", "sofia"
        )
        fake.events[FAMILY][-1]["shift_id"] = "mattina"
        ha_server, client, _ = await started(fake)
        try:
            child = await connect(client, CHILD_USER)
            removed = await request(
                child,
                {
                    "id": 1,
                    "op": "shifts_apply",
                    "person": "sofia",
                    "shift_id": "",
                    "days": ["2031-05-05"],
                },
            )
            assert removed["result"] == {"removed": 1, "inserted": 0}
            assert all(e["shift_id"] == "" for e in fake.events[FAMILY])
            assert [c["service"] for c in fake.calls][-1] == "delete_event"
            await child.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_night_shift_ends_the_next_day_and_others_are_refused() -> None:
    async def scenario() -> None:
        fake = _fake_with_shifts()
        ha_server, client, _ = await started(fake)
        try:
            mamma = await connect(client, ADULT_USER)
            reply = await request(
                mamma,
                {
                    "id": 1,
                    "op": "shifts_apply",
                    "person": "mamma",
                    "shift_id": "nt",
                    "days": ["2031-06-06"],
                },
            )
            assert reply["ok"] is True
            (add,) = [c["data"] for c in fake.calls if c["service"] == "add_event"]
            assert add["start"] == "2031-06-06 22:00:00"
            assert add["end"] == "2031-06-07 06:00:00"
            await mamma.close()
            child = await connect(client, CHILD_USER)
            other = await request(
                child,
                {
                    "id": 2,
                    "op": "shifts_apply",
                    "person": "mamma",
                    "shift_id": "nt",
                    "days": ["2031-06-06"],
                },
            )
            assert other["error"] == "forbidden"
            unknown = await request(
                child,
                {
                    "id": 3,
                    "op": "shifts_apply",
                    "person": "sofia",
                    "shift_id": "nope",
                    "days": ["2031-06-06"],
                },
            )
            assert unknown["error"] == "not_found"
            await child.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)
