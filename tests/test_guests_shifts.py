"""Invites, 0.9.0b8: a guest with its own work shifts (a grandmother who still works). Names are
invented."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from aiohttp.test_utils import TestClient
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from test_guests import (  # noqa: F401 - the fixtures are used by name
    API,
    _activate,
    _auth,
    _day,
    _invite,
    _list,
    _manager,
    _unlimited,
    _ws,
    client,
    family,
    fresh_limits,
    no_real_push,
)


@pytest.fixture
def expected_lingering_timers() -> bool:
    return True  # the adults' notice of changed shifts waits two minutes


TYPES = [
    {"name": "Mattina", "start": "06:00", "end": "14:00"},
    {"name": "Pomeriggio", "start": "14:00", "end": "22:00"},
    {"name": "Notte", "start": "22:00", "end": "06:00"},
]


async def _worker(
    hass: HomeAssistant, http: TestClient, ws: Any, name: str = "Nonna Lavoratrice", **kw: Any
) -> tuple[str, str]:
    """A phone of a guest who has its own shifts, confirmed by an adult."""
    _unlimited(hass)
    _, invite_token = await _invite(
        hass,
        ws,
        name=name,
        has_shifts=True,
        shift_color="#0EA5E9",
        shifts_category="asilo",
        **kw,
    )
    token = (await (await _activate(http, invite_token)).json())["token"]
    family_entry = hass.config_entries.async_entries("family_hub")[0]
    (device_id,) = [d for d, v in _manager(family_entry).devices.items() if v["name"] == name]
    await _ws(hass, ws, "device_confirm", device_id=device_id, accept=True)
    await hass.async_block_till_done()  # the new guest person reloads the entry
    _unlimited(hass)
    return device_id, token


async def _shifts(http: TestClient, token: str) -> dict[str, Any]:
    answer = await http.get(
        f"{API}shifts", params={"from": _day(0), "days": "28"}, headers=_auth(token)
    )
    assert answer.status == 200, await answer.text()
    return await answer.json()


async def test_a_guest_person_is_made_for_its_shifts(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    device_id, token = await _worker(hass, client, hass_ws_client)
    device = _manager(family).devices[device_id]
    person = next(p for p in family.options["persons"] if p["id"] == device["person_id"])
    assert person["name"] == "Nonna Lavoratrice" and person["color"] == "#0EA5E9"
    assert person["role"] == "guest" and person["has_shifts"] is True
    assert "ha_user_id" not in person
    me = await (await client.get(f"{API}me", headers=_auth(token))).json()
    assert me["has_shifts"] is True and me["own_person"] == person["id"]
    # In the calendar's person list (the family's filter).
    state = hass.states.get("calendar.family_hub_asilo")
    listed = {p["id"]: p for p in state.attributes["persons"]}
    assert listed[person["id"]]["has_shifts"] is True


async def test_shifts_from_the_web_app_days_and_rotation(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    device_id, token = await _worker(hass, client, hass_ws_client)
    answer = await client.put(f"{API}shifts/types", json={"types": TYPES}, headers=_auth(token))
    assert answer.status == 200
    await hass.async_block_till_done()
    types = {t["name"]: t["id"] for t in (await _shifts(client, token))["types"]}
    assert set(types) == {"Mattina", "Pomeriggio", "Notte"}
    # One day.
    answer = await client.post(
        f"{API}shifts/apply",
        json={"days": [_day(1)], "shift_id": types["Mattina"]},
        headers=_auth(token),
    )
    assert (await answer.json()) == {"written": 1}
    # A rotation: Mattina, Mattina, Notte, riposo, from the day after, for 8 days.
    pattern = [types["Mattina"], types["Mattina"], types["Notte"], ""]
    answer = await client.post(
        f"{API}shifts/rotation",
        json={"start": _day(2), "pattern": pattern, "days": 8},
        headers=_auth(token),
    )
    assert (await answer.json()) == {"written": 6}
    days = (await _shifts(client, token))["days"]
    by_day = {d["date"]: d["name"] for d in days}
    assert by_day[_day(1)] == "Mattina"
    assert [by_day.get(_day(2 + i), "riposo") for i in range(8)] == [
        "Mattina",
        "Mattina",
        "Notte",
        "riposo",
        "Mattina",
        "Mattina",
        "Notte",
        "riposo",
    ]
    # A single day changed afterwards (a free day).
    await client.post(
        f"{API}shifts/apply", json={"days": [_day(2)], "shift_id": ""}, headers=_auth(token)
    )
    by_day = {d["date"]: d["name"] for d in (await _shifts(client, token))["days"]}
    assert _day(2) not in by_day
    # The night ends the next morning.
    night = next(d for d in (await _shifts(client, token))["days"] if d["name"] == "Notte")
    assert night["end"][:10] > night["start"][:10]
    # The guest sees its shifts in its own list too.
    titles = [e["title"] for e in (await (await _list(client, token)).json())["events"]]
    assert "Nonna Lavoratrice · Mattina" in titles


async def test_adults_see_the_shifts_other_guests_only_when_chosen(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    device_id, token = await _worker(hass, client, hass_ws_client)
    await client.put(f"{API}shifts/types", json={"types": TYPES[:1]}, headers=_auth(token))
    await hass.async_block_till_done()
    (mattina,) = (await _shifts(client, token))["types"]
    await client.post(
        f"{API}shifts/apply",
        json={"days": [_day(1)], "shift_id": mattina["id"]},
        headers=_auth(token),
    )
    person_id = _manager(family).devices[device_id]["person_id"]
    # Adults: in Family Hub's calendar.
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": "calendar.family_hub_asilo",
            "start_date_time": f"{_day(0)} 00:00:00",
            "end_date_time": f"{_day(3)} 00:00:00",
        },
        blocking=True,
        return_response=True,
    )
    events = response["calendar.family_hub_asilo"]["events"]
    assert any(e["summary"] == "Nonna Lavoratrice · Mattina" for e in events)
    assert any(
        r["summary"] == "Nonna Lavoratrice · Mattina" and r["persons"] == [person_id]
        for r in family.runtime_data.store.events.values()
    )
    # Another guest who sees Sofia in "asilo": not the grandmother's shifts.
    _, other_invite = await _invite(
        hass, hass_ws_client, name="Zio", persons=["sofia"], categories=["asilo"]
    )
    other = (await (await _activate(client, other_invite)).json())["token"]
    manager = _manager(family)
    zio = next(d for d, v in manager.devices.items() if v["name"] == "Zio")
    await _ws(hass, hass_ws_client, "device_confirm", device_id=zio, accept=True)
    await hass.async_block_till_done()
    _unlimited(hass)
    text = json.dumps(await (await _list(client, other)).json())
    assert "Mattina" not in text and person_id not in text
    # Chosen among its visible persons: now it sees them.
    await _ws(
        hass,
        hass_ws_client,
        "device_update",
        device_id=zio,
        changes={"persons": ["sofia", person_id]},
    )
    titles = [e["title"] for e in (await (await _list(client, other)).json())["events"]]
    assert titles == ["Nonna Lavoratrice · Mattina"]
    # And the other guest cannot touch them.
    answer = await client.get(f"{API}shifts", params={"from": _day(0)}, headers=_auth(other))
    assert answer.status == 403


async def test_a_guest_cannot_change_shifts_that_are_not_its_own(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    _, token = await _worker(hass, client, hass_ws_client)
    for path, body in (
        ("shifts/types", {"types": TYPES, "person": "sofia"}),
        ("shifts/apply", {"days": [_day(1)], "shift_id": "", "person": "mamma"}),
        ("shifts/rotation", {"start": _day(1), "pattern": [""], "days": 2, "person": "mamma"}),
    ):
        method = client.put if path == "shifts/types" else client.post
        answer = await method(f"{API}{path}", json=body, headers=_auth(token))
        assert answer.status == 403, path
    # A shift type of someone else is not one of its own.
    answer = await client.post(
        f"{API}shifts/apply", json={"days": [_day(1)], "shift_id": "altrui"}, headers=_auth(token)
    )
    assert answer.status == 422
    # A Family Hub shift of Mamma on that day stays untouched.
    await hass.services.async_call(
        "family_hub",
        "add_event",
        {
            "category": "asilo",
            "summary": "Turno di Mamma",
            "persons": ["mamma"],
            "start": f"{_day(1)} 08:00:00",
            "end": f"{_day(1)} 16:00:00",
            "shift_id": "m1",
        },
        blocking=True,
    )
    await client.post(
        f"{API}shifts/apply", json={"days": [_day(1)], "shift_id": ""}, headers=_auth(token)
    )
    assert any(r["summary"] == "Turno di Mamma" for r in family.runtime_data.store.events.values())
    # A phone without its own shifts has no shifts at all.
    _, plain = await _invite(hass, hass_ws_client, name="Zia")
    plain_token = (await (await _activate(client, plain)).json())["token"]
    zia = next(d for d, v in _manager(family).devices.items() if v["name"] == "Zia")
    await _ws(hass, hass_ws_client, "device_confirm", device_id=zia, accept=True)
    answer = await client.get(f"{API}shifts", params={"from": _day(0)}, headers=_auth(plain_token))
    assert answer.status == 403


async def test_adults_hear_once_that_the_shifts_changed(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    calls: list[Any] = []
    hass.services.async_register("notify", "mobile_app_telefono_mamma", calls.append)
    _, token = await _worker(hass, client, hass_ws_client)
    await client.put(f"{API}shifts/types", json={"types": TYPES[:1]}, headers=_auth(token))
    await hass.async_block_till_done()
    (mattina,) = (await _shifts(client, token))["types"]
    calls.clear()
    for day in (1, 2, 3):
        await client.post(
            f"{API}shifts/apply",
            json={"days": [_day(day)], "shift_id": mattina["id"]},
            headers=_auth(token),
        )
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=3))
    await hass.async_block_till_done()
    messages = [c.data["message"] for c in calls]
    assert messages == ["Nonna Lavoratrice ha aggiornato i turni della prossima settimana"]
    # Switched off in "Chi riceve le richieste": no more.
    await _ws(
        hass,
        hass_ws_client,
        "recipients_save",
        recipients={"mode": "adults", "persons": [], "shifts": False},
    )
    calls.clear()
    await client.post(
        f"{API}shifts/apply", json={"days": [_day(4)], "shift_id": ""}, headers=_auth(token)
    )
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await hass.async_block_till_done()
    assert calls == []


async def test_removing_the_phone_keeps_or_deletes_the_shifts(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    for keep in (True, False):
        name = f"Nonna {'tiene' if keep else 'cancella'}"
        device_id, token = await _worker(hass, client, hass_ws_client, name=name)
        await client.put(f"{API}shifts/types", json={"types": TYPES[:1]}, headers=_auth(token))
        await hass.async_block_till_done()
        (mattina,) = (await _shifts(client, token))["types"]
        await client.post(
            f"{API}shifts/apply",
            json={"days": [_day(1)], "shift_id": mattina["id"]},
            headers=_auth(token),
        )
        person_id = _manager(family).devices[device_id]["person_id"]
        await _ws(hass, hass_ws_client, "device_disable", device_id=device_id)
        # The adult must say what happens to the shifts.
        answer = await _ws(hass, hass_ws_client, "device_remove", device_id=device_id)
        assert answer["error"]["code"] == "keep_shifts"
        answer = await _ws(
            hass, hass_ws_client, "device_remove", device_id=device_id, keep_shifts=keep
        )
        assert answer["success"]
        await hass.async_block_till_done()
        persons = {p["id"] for p in family.options["persons"]}
        shifts_left = [
            r
            for r in family.runtime_data.store.events.values()
            if person_id in (r.get("persons") or [])
        ]
        assert (person_id in persons) is keep
        assert bool(shifts_left) is keep


async def test_a_new_phone_keeps_the_person_and_its_shifts(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    old_id, token = await _worker(hass, client, hass_ws_client)
    person_id = _manager(family).devices[old_id]["person_id"]
    result = (await _ws(hass, hass_ws_client, "device_replace", device_id=old_id))["result"]
    new_token = (await (await _activate(client, result["link"].split("#i=")[1])).json())["token"]
    new_id = next(d for d in _manager(family).devices if d != old_id)
    await _ws(hass, hass_ws_client, "device_confirm", device_id=new_id, accept=True)
    await hass.async_block_till_done()
    _unlimited(hass)
    assert _manager(family).devices[new_id]["person_id"] == person_id
    assert [p["id"] for p in family.options["persons"]].count(person_id) == 1
    assert (
        await client.get(f"{API}shifts", params={"from": _day(0)}, headers=_auth(new_token))
    ).status == 200
