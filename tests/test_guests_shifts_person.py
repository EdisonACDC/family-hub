"""0.10.2: the shifts of a guest can be a person of the family's ("I suoi turni sono di"): her
models and her shifts, the same as the panel's; what the web app saves goes onto her; no guest
person is made. A guest that already has a guest person can be moved onto her. Rule zero: linking
a person gives no appointments of persons or calendars that were not chosen. Names are invented."""

from __future__ import annotations

from typing import Any

import pytest
from aiohttp.test_utils import TestClient
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_guests import (  # noqa: F401 - the fixtures are used by name
    API,
    _activate,
    _auth,
    _day,
    _invite,
    _manager,
    _unlimited,
    _ws,
    client,
    family,  # noqa: F811
    fresh_limits,
    no_real_push,
)

from custom_components.family_hub.const import DOMAIN, OPT_SHIFTS


@pytest.fixture
def expected_lingering_timers() -> bool:
    return True


K3 = {"id": "k3", "name": "K3", "start": "06:00", "end": "14:00", "category": "lavoro"}
SK3 = {"id": "sk3", "name": "SK3", "start": "14:00", "end": "22:00", "category": "lavoro"}


async def _mamma_works(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Mamma has her models (in the "lavoro" calendar) and a shift tomorrow, as in the panel."""
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, OPT_SHIFTS: {"mamma": [K3, SK3]}}
    )
    await hass.async_block_till_done()
    await hass.services.async_call(
        DOMAIN,
        "add_event",
        {
            "category": "lavoro",
            "summary": "K3",
            "persons": ["mamma"],
            "shift_id": "k3",
            "start": f"{_day(1)} 06:00:00",
            "end": f"{_day(1)} 14:00:00",
        },
        blocking=True,
    )


async def _phone(
    hass: HomeAssistant, http: TestClient, ws: Any, name: str, **invite: Any
) -> tuple[str, str]:
    _unlimited(hass)
    _, invite_token = await _invite(hass, ws, name=name, **invite)
    token = (await (await _activate(http, invite_token)).json())["token"]
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    (device_id,) = [d for d, v in _manager(entry).devices.items() if v["name"] == name]
    await _ws(hass, ws, "device_confirm", device_id=device_id, accept=True)
    await hass.async_block_till_done()
    _unlimited(hass)
    return device_id, token


def _events(entry: MockConfigEntry) -> list[dict[str, Any]]:
    return list(entry.runtime_data.store.events.values())


async def test_shifts_of_a_person_of_the_family(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    await _mamma_works(hass, family)
    device_id, token = await _phone(
        hass,
        client,
        hass_ws_client,
        "Tata Prova",
        persons=["sofia", "mamma"],
        categories=["scuola", "asilo"],
        has_shifts=True,
        shifts_category="asilo",
        shifts_person="mamma",
    )
    persons_before = [p["id"] for p in family.options["persons"]]
    device = _manager(family).devices[device_id]
    # No guest person: the shifts are Mamma's.
    assert device["person_id"] == "mamma" and device["shifts_person"] == "mamma"
    assert [p["id"] for p in family.options["persons"]] == persons_before
    assert all(p["role"] != "guest" for p in family.options["persons"])
    me = await (await client.get(f"{API}me", headers=_auth(token))).json()
    assert me["has_shifts"] is True and me["own_person"] == "mamma"
    # The models and the shifts of Mamma, the same as the panel's.
    answer = await client.get(
        f"{API}shifts", params={"from": _day(0), "days": "14"}, headers=_auth(token)
    )
    assert answer.status == 200
    data = await answer.json()
    assert [(t["id"], t["name"]) for t in data["types"]] == [("k3", "K3"), ("sk3", "SK3")]
    assert [(d["date"], d["name"]) for d in data["days"]] == [(_day(1), "K3")]
    # What it puts on a day is written as the panel writes it, on Mamma.
    answer = await client.post(
        f"{API}shifts/apply",
        json={"days": [_day(3)], "shift_id": "sk3"},
        headers=_auth(token),
    )
    assert answer.status == 200 and (await answer.json())["written"] == 1
    await hass.async_block_till_done()
    written = [r for r in _events(family) if str(r["start"])[:10] == _day(3)]
    assert [(r["summary"], r["persons"], r["category"], r["shift_id"]) for r in written] == [
        ("SK3", ["mamma"], "lavoro", "sk3")
    ]
    # Changing the models keeps each one's calendar; a new one goes to the invite's.
    types = [
        {"id": "k3", "name": "K3", "start": "07:00", "end": "15:00"},
        {"id": "sk3", "name": "SK3", "start": "14:00", "end": "22:00"},
        {"name": "Spezzato", "start": "08:00", "end": "12:00"},
    ]
    answer = await client.put(f"{API}shifts/types", json={"types": types}, headers=_auth(token))
    assert answer.status == 200
    await hass.async_block_till_done()
    saved = {t["name"]: t for t in family.options[OPT_SHIFTS]["mamma"]}
    assert saved["K3"]["category"] == "lavoro" and saved["K3"]["start"] == "07:00"
    assert saved["Spezzato"]["category"] == "asilo"
    assert [p["id"] for p in family.options["persons"]] == persons_before
    # Asking for anyone else's shifts is refused.
    answer = await client.post(
        f"{API}shifts/apply",
        json={"person": "sofia", "days": [_day(4)], "shift_id": "k3"},
        headers=_auth(token),
    )
    assert answer.status == 403


async def test_linking_a_person_gives_no_other_appointments(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    await _mamma_works(hass, family)
    for summary, category, persons in (
        ("RIUNIONE-RISERVATA", "lavoro", ["mamma"]),  # her appointment in a calendar not chosen
        ("Dal dottore", "scuola", ["mamma"]),  # in a calendar that is chosen
        ("SOLO-SOFIA-DOTTORE", "dottore", ["sofia"]),  # a person chosen, calendar not
    ):
        await hass.services.async_call(
            DOMAIN,
            "add_event",
            {
                "category": category,
                "summary": summary,
                "persons": persons,
                "start": f"{_day(2)} 10:00:00",
                "end": f"{_day(2)} 11:00:00",
            },
            blocking=True,
        )
    _, token = await _phone(
        hass,
        client,
        hass_ws_client,
        "Tata Prova",
        persons=["sofia", "mamma"],
        categories=["scuola"],
        has_shifts=True,
        shifts_category="scuola",
        shifts_person="mamma",
    )
    answer = await client.get(
        f"{API}events", params={"from": _day(0), "days": "7"}, headers=_auth(token)
    )
    text = await answer.text()
    titles = sorted(e["title"] for e in (await answer.json())["events"])
    # Her shift (whatever the calendar) and what is in the chosen calendar; nothing else.
    assert titles == ["Dal dottore", "K3"]
    assert "RIUNIONE-RISERVATA" not in text and "SOLO-SOFIA" not in text


async def test_the_person_must_be_one_the_guest_sees(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    for person in ("mamma", "sconosciuta"):
        answer = await _ws(
            hass,
            hass_ws_client,
            "invite_create",
            invite={
                "name": "Tata",
                "persons": ["sofia"],
                "categories": ["scuola"],
                "has_shifts": True,
                "shifts_person": person,
            },
        )
        assert not answer["success"], person
    # Without "has shifts" the choice is ignored.
    answer = await _ws(
        hass,
        hass_ws_client,
        "invite_create",
        invite={
            "name": "Tata",
            "persons": ["sofia"],
            "categories": ["scuola"],
            "has_shifts": False,
            "shifts_person": "mamma",
        },
    )
    assert answer["success"]
    invite = next(
        i
        for i in (await _ws(hass, hass_ws_client, "list"))["result"]["invites"]
        if i["name"] == "Tata"
    )
    assert invite["shifts_person"] == ""


async def test_a_guest_person_moves_onto_the_person(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    """Veronica has a guest person with her own models and shifts. The adult says the shifts are
    Mamma's: models and shifts move onto Mamma (a day she already has a shift on keeps hers),
    and the guest person goes away."""
    await _mamma_works(hass, family)
    device_id, token = await _phone(
        hass,
        client,
        hass_ws_client,
        "Veronica",
        persons=["sofia"],
        categories=["scuola", "asilo"],
        has_shifts=True,
        shifts_category="asilo",
    )
    guest = _manager(family).devices[device_id]["person_id"]
    assert guest.startswith("guest_")
    types = [
        {"name": "K3", "start": "06:00", "end": "14:00"},  # the same name as Mamma's
        {"name": "Mattina", "start": "05:00", "end": "13:00"},  # not hers: added
    ]
    await client.put(f"{API}shifts/types", json={"types": types}, headers=_auth(token))
    await hass.async_block_till_done()
    mine = {t["name"]: t["id"] for t in (await _shifts(client, token))["types"]}
    for day, name in ((1, "K3"), (2, "Mattina"), (3, "K3")):  # day 1 Mamma already has a shift
        await client.post(
            f"{API}shifts/apply",
            json={"days": [_day(day)], "shift_id": mine[name]},
            headers=_auth(token),
        )
    await hass.async_block_till_done()

    answer = await _ws(
        hass,
        hass_ws_client,
        "device_update",
        device_id=device_id,
        changes={"persons": ["sofia", "mamma"], "shifts_person": "mamma"},
    )
    assert answer["success"], answer
    await hass.async_block_till_done()

    assert guest not in {p["id"] for p in family.options["persons"]}
    assert guest not in family.options[OPT_SHIFTS]
    models = {m["name"]: m for m in family.options[OPT_SHIFTS]["mamma"]}
    assert set(models) == {"K3", "SK3", "Mattina"} and models["K3"]["id"] == "k3"
    device = _manager(family).devices[device_id]
    assert device["person_id"] == "mamma" and "mamma" in device["persons"]
    shifts = sorted(
        (str(r["start"])[:10], r["summary"], tuple(r["persons"]), r["shift_id"])
        for r in _events(family)
        if r.get("shift_id")
    )
    assert shifts == [
        (_day(1), "K3", ("mamma",), "k3"),  # hers, kept
        (_day(2), "Mattina", ("mamma",), models["Mattina"]["id"]),
        (_day(3), "K3", ("mamma",), "k3"),
    ]
    assert all(guest not in (r.get("persons") or []) for r in _events(family))
    # The web app now works on Mamma's shifts.
    data = await _shifts(client, token)
    assert {t["name"] for t in data["types"]} == {"K3", "SK3", "Mattina"}
    me = await (await client.get(f"{API}me", headers=_auth(token))).json()
    assert me["own_person"] == "mamma"


async def test_removing_the_phone_never_touches_the_person(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    await _mamma_works(hass, family)
    device_id, _ = await _phone(
        hass,
        client,
        hass_ws_client,
        "Tata Prova",
        persons=["sofia", "mamma"],
        categories=["scuola"],
        has_shifts=True,
        shifts_category="scuola",
        shifts_person="mamma",
    )
    await _ws(hass, hass_ws_client, "device_disable", device_id=device_id)
    # Nothing to ask about the shifts: they are Mamma's, not the phone's.
    for step in (False, True):
        answer = await _ws(
            hass,
            hass_ws_client,
            "device_remove",
            device_id=device_id,
            **({"keep_shifts": False} if step else {}),
        )
        if answer["success"]:
            break
        assert answer["error"]["code"] == "keep_shifts"
    assert answer["success"], answer
    await hass.async_block_till_done()
    assert "mamma" in {p["id"] for p in family.options["persons"]}
    assert "guest_device" not in next(p for p in family.options["persons"] if p["id"] == "mamma")
    assert [m["id"] for m in family.options[OPT_SHIFTS]["mamma"]] == ["k3", "sk3"]
    assert [r["summary"] for r in _events(family) if r.get("shift_id")] == ["K3"]


async def _shifts(http: TestClient, token: str) -> dict[str, Any]:
    answer = await http.get(
        f"{API}shifts", params={"from": _day(0), "days": "28"}, headers=_auth(token)
    )
    assert answer.status == 200, await answer.text()
    return await answer.json()
