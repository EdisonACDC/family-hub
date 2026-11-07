"""Shift models: validation, the save command, and updates of events already entered."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.family_hub.const import (
    CONF_FAMILY_NAME,
    CONF_FIRST_WEEKDAY,
    CONF_LANGUAGE,
    DOMAIN,
    OPT_CATEGORIES,
    OPT_PERSONS,
    OPT_SHIFTS,
)
from custom_components.family_hub.shifts import ShiftError, clean_shifts, crosses_midnight

CAT = {"famiglia"}
CAL = "calendar.family_hub_famiglia"


def _shift(**overrides: Any) -> dict[str, Any]:
    shift: dict[str, Any] = {
        "name": "Mattina",
        "start": "06:00",
        "end": "14:00",
        "category": "famiglia",
    }
    shift.update(overrides)
    return shift


def test_valid_shift_gets_a_stable_id() -> None:
    (cleaned,) = clean_shifts([_shift()], CAT)
    assert cleaned["name"] == "Mattina" and cleaned["id"]
    assert clean_shifts([{**cleaned}], CAT)[0]["id"] == cleaned["id"]


@pytest.mark.parametrize(
    "bad",
    [
        _shift(name=""),
        _shift(name="x" * 61),
        _shift(start="7.30"),
        _shift(end="25:00"),
        _shift(start="08:00", end="08:00"),
        _shift(category="sport"),
    ],
)
def test_invalid_shift_is_refused(bad: dict[str, Any]) -> None:
    with pytest.raises(ShiftError):
        clean_shifts([bad], CAT)


def test_names_are_unique_per_person_ignoring_case() -> None:
    with pytest.raises(ShiftError, match="already used"):
        clean_shifts([_shift(name="Mattina"), _shift(name="mattina")], CAT)


def test_a_shift_can_run_past_midnight() -> None:
    (night,) = clean_shifts([_shift(name="N", start="22:00", end="06:00")], CAT)
    assert crosses_midnight(night)
    assert not crosses_midnight(clean_shifts([_shift()], CAT)[0])


async def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={},
        options={
            CONF_FAMILY_NAME: "Esempio",
            CONF_LANGUAGE: "it",
            CONF_FIRST_WEEKDAY: "monday",
            OPT_PERSONS: [{"id": "mamma", "name": "Mamma", "color": "#2563EB", "role": "adult"}],
            OPT_CATEGORIES: [{"id": "famiglia", "name": "Famiglia", "color": "#3B82F6"}],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _add(hass: HomeAssistant, start: str, end: str, shift_id: str) -> None:
    await hass.services.async_call(
        DOMAIN,
        "add_event",
        {
            "category": "famiglia",
            "summary": "Mattina",
            "start": start,
            "end": end,
            "persons": ["mamma"],
            "shift_id": shift_id,
        },
        blocking=True,
    )


async def _save(
    client: Any, msg_id: int, shifts: list[dict[str, Any]], apply_future: bool = False
) -> dict[str, Any]:
    await client.send_json(
        {
            "id": msg_id,
            "type": "family_hub/shifts/save",
            "person": "mamma",
            "shifts": shifts,
            "apply_future": apply_future,
        }
    )
    return await client.receive_json()


async def test_save_stores_only_the_shifts(hass: HomeAssistant, hass_ws_client: Any) -> None:
    entry = await _entry(hass)
    client = await hass_ws_client(hass)
    reply = await _save(client, 1, [_shift(), _shift(name="Notte", start="22:00", end="06:00")])
    assert reply["success"] is True, reply
    assert [s["name"] for s in entry.options[OPT_SHIFTS]["mamma"]] == ["Mattina", "Notte"]
    assert entry.options[CONF_FAMILY_NAME] == "Esempio"  # the rest of the setup is untouched


async def test_save_refuses_unknown_person_and_bad_shift(
    hass: HomeAssistant, hass_ws_client: Any
) -> None:
    await _entry(hass)
    client = await hass_ws_client(hass)
    await client.send_json(
        {
            "id": 1,
            "type": "family_hub/shifts/save",
            "person": "nessuno",
            "shifts": [],
            "apply_future": False,
        }
    )
    assert (await client.receive_json())["error"]["code"] == "not_found"
    reply = await _save(client, 2, [_shift(start="7.30")])
    assert reply["success"] is False and reply["error"]["code"] == "invalid_config"


async def test_non_admin_cannot_delete_shifts(
    hass: HomeAssistant, hass_ws_client: Any, hass_read_only_access_token: str
) -> None:
    entry = await _entry(hass)
    await _save(await hass_ws_client(hass), 1, [_shift()])
    client = await hass_ws_client(hass, hass_read_only_access_token)
    reply = await _save(client, 2, [])
    assert reply["success"] is False
    assert [s["name"] for s in entry.options[OPT_SHIFTS]["mamma"]] == ["Mattina"]


async def test_time_change_updates_only_future_events_when_asked(
    hass: HomeAssistant, hass_ws_client: Any
) -> None:
    entry = await _entry(hass)
    client = await hass_ws_client(hass)
    reply = await _save(client, 1, [_shift()])
    shift_id = entry.options[OPT_SHIFTS]["mamma"][0]["id"]
    await _add(hass, "2020-01-10 07:30:00", "2020-01-10 13:30:00", shift_id)  # past
    await _add(hass, "2030-01-10 07:30:00", "2030-01-10 13:30:00", shift_id)  # future
    await _add(hass, "2030-01-11 07:30:00", "2030-01-11 13:30:00", "")  # not a shift

    moved = [{**entry.options[OPT_SHIFTS]["mamma"][0], "start": "08:00", "end": "15:00"}]
    reply = await _save(client, 2, moved, apply_future=False)
    assert reply["result"]["updated"] == 0
    store = entry.runtime_data.store.events
    future = [r for r in store.values() if r["start"].startswith("2030-01-10")][0]
    assert future["start"].startswith("2030-01-10T07:30")

    # A later change, confirmed: the future event follows the model.
    later = [{**moved[0], "end": "16:00"}]
    reply = await _save(client, 3, later, apply_future=True)
    assert reply["result"]["updated"] == 1
    future = [
        r for r in entry.runtime_data.store.events.values() if r["start"].startswith("2030-01-10")
    ][0]
    assert future["start"].startswith("2030-01-10T08:00")
    assert future["end"].startswith("2030-01-10T16:00")
    past = [r for r in store.values() if r["start"].startswith("2020-01-10")][0]
    assert past["start"].startswith("2020-01-10T07:30")
    untouched = [r for r in store.values() if r["start"].startswith("2030-01-11")][0]
    assert untouched["start"].startswith("2030-01-11T07:30")


async def test_overnight_change_ends_the_next_day(hass: HomeAssistant, hass_ws_client: Any) -> None:
    entry = await _entry(hass)
    client = await hass_ws_client(hass)
    await _save(client, 1, [_shift()])
    shift_id = entry.options[OPT_SHIFTS]["mamma"][0]["id"]
    await _add(hass, "2030-02-01 07:30:00", "2030-02-01 13:30:00", shift_id)
    night = {**entry.options[OPT_SHIFTS]["mamma"][0], "name": "N", "start": "22:00", "end": "06:00"}
    await _save(client, 2, [night], apply_future=True)
    (record,) = entry.runtime_data.store.events.values()
    assert record["summary"] == "N"
    assert record["start"].startswith("2030-02-01T22:00")
    assert record["end"].startswith("2030-02-02T06:00")


async def test_removing_a_shift_keeps_its_events(hass: HomeAssistant, hass_ws_client: Any) -> None:
    entry = await _entry(hass)
    client = await hass_ws_client(hass)
    await _save(client, 1, [_shift()])
    shift_id = entry.options[OPT_SHIFTS]["mamma"][0]["id"]
    await _add(hass, "2030-03-01 07:30:00", "2030-03-01 13:30:00", shift_id)
    await _save(client, 2, [], apply_future=True)
    assert entry.options[OPT_SHIFTS]["mamma"] == []
    assert len(entry.runtime_data.store.events) == 1
