"""Hand-made rubbish pickups in Home Assistant: the read-only calendar that shows them, the evening
reminder before a pickup, and the commands that save them (admins only, checked before saving)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)
from pytest_homeassistant_custom_component.plugins import WebSocketGenerator

from custom_components.family_hub.const import (
    CONF_FAMILY_NAME,
    CONF_FIRST_WEEKDAY,
    CONF_LANGUAGE,
    DOMAIN,
    OPT_CATEGORIES,
    OPT_MANUAL_WASTE,
    OPT_PERSONS,
    OPT_REMINDERS,
)

CALENDAR = "calendar.family_hub_ext_manualwaste"
BIWEEKLY = {
    "rules": [{"type": "bio", "frequency": "biweekly", "weekday": "tue", "first": "2026-11-03"}],
    "extra": [],
    "skip": [],
    "moves": [],
}


def _entry(schedule: dict[str, Any] | None) -> MockConfigEntry:
    options: dict[str, Any] = {
        OPT_PERSONS: [],
        OPT_CATEGORIES: [{"id": "famiglia", "name": "Famiglia", "color": "#3B82F6"}],
        CONF_LANGUAGE: "it",
        OPT_REMINDERS: {"channels": ["tablet"], "quiet_start": None, "quiet_end": None},
    }
    if schedule is not None:
        options[OPT_MANUAL_WASTE] = schedule
    return MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
        options=options,
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _days(hass: HomeAssistant, start: str, end: str) -> list[str]:
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {"start_date_time": start, "end_date_time": end},
        target={"entity_id": CALENDAR},
        blocking=True,
        return_response=True,
    )
    return [event["summary"] for event in response[CALENDAR]["events"]]


async def test_the_pickups_are_a_read_only_calendar_found_in_the_registry(
    hass: HomeAssistant,
) -> None:
    entry = _entry(BIWEEKLY)
    await _setup(hass, entry)
    registry = er.async_get(hass)
    item = registry.async_get(CALENDAR)
    assert item is not None and item.platform == DOMAIN
    assert item.unique_id == f"{entry.entry_id}_ext_manualwaste"
    # The calendar shows the pickups on the days the family gave.
    assert await _days(hass, "2026-11-17T00:00:00+01:00", "2026-11-18T00:00:00+01:00") == [
        "Organico"
    ]
    assert await _days(hass, "2026-11-10T00:00:00+01:00", "2026-11-11T00:00:00+01:00") == []


async def test_the_evening_before_a_pickup_is_announced(hass: HomeAssistant, freezer: Any) -> None:
    """The example: a pickup every 2 weeks from Tuesday 3 November; on Monday evening the 2nd the
    family is told it is tomorrow."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-11-02 12:00:00+01:00")
    calls = async_mock_service(hass, "persistent_notification", "create")
    await _setup(hass, _entry(BIWEEKLY))
    freezer.move_to("2026-11-02 19:00:00+01:00")
    async_fire_time_changed(hass, datetime.fromisoformat("2026-11-02 19:00:00+01:00"))
    await hass.async_block_till_done()
    assert "Domani: Organico" in [c.data["message"] for c in calls]


async def test_a_saved_skip_takes_the_pickup_off_the_calendar_at_once(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    await _setup(hass, _entry(BIWEEKLY))
    client = await hass_ws_client(hass)
    schedule = {**BIWEEKLY, "skip": [{"type": "bio", "date": "2026-11-17"}]}
    await client.send_json({"id": 1, "type": "family_hub/manual_waste/save", "schedule": schedule})
    reply = await client.receive_json()
    assert reply["success"] is True, reply
    assert await _days(hass, "2026-11-17T00:00:00+01:00", "2026-11-18T00:00:00+01:00") == []
    assert await _days(hass, "2026-12-01T00:00:00+01:00", "2026-12-02T00:00:00+01:00") == [
        "Organico"
    ]


async def test_a_schedule_that_cannot_be_used_is_refused_and_nothing_changes(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    entry = _entry(BIWEEKLY)
    await _setup(hass, entry)
    client = await hass_ws_client(hass)
    bad = {
        **BIWEEKLY,
        "rules": [
            {"type": "bio", "frequency": "biweekly", "weekday": "wed", "first": "2026-11-03"}
        ],
    }
    await client.send_json({"id": 2, "type": "family_hub/manual_waste/save", "schedule": bad})
    reply = await client.receive_json()
    assert reply["success"] is False
    assert reply["error"]["message"] == "weekday_mismatch"
    assert entry.options[OPT_MANUAL_WASTE] == BIWEEKLY


async def test_the_page_gets_the_schedule_and_the_types_it_can_use(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    await _setup(hass, _entry(BIWEEKLY))
    client = await hass_ws_client(hass)
    await client.send_json({"id": 3, "type": "family_hub/manual_waste/get"})
    reply = await client.receive_json()
    assert reply["success"] is True
    assert reply["result"]["schedule"]["rules"][0]["type"] == "bio"
    ids = [kind["id"] for kind in reply["result"]["types"]]
    assert "bio" in ids and "restmuell" in ids


async def test_a_pickup_is_in_the_day_summary_like_a_downloaded_one(hass: HomeAssistant) -> None:
    """The summary of the day before says "Rifiuti: Organico", as it does for a file's pickups."""
    from datetime import date

    await _setup(hass, _entry(BIWEEKLY))
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    lines = await entry.runtime_data.external.async_day_lines(date(2026, 11, 3))
    assert ("Rifiuti: Organico", []) in lines


async def test_the_list_of_external_calendars_includes_the_pickups_made_by_hand(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """The panel's list (family_hub/ics/list) carries the pickups' calendar with every field the
    panel and the status use, so it is shown like a file or a link, with its own origin."""
    await _setup(hass, _entry(BIWEEKLY))
    client = await hass_ws_client(hass)
    await client.send_json({"id": 4, "type": "family_hub/ics/list"})
    reply = await client.receive_json()
    assert reply["success"] is True, reply
    found = [c for c in reply["result"]["calendars"] if c["id"] == "manualwaste"]
    assert len(found) == 1, reply["result"]["calendars"]
    calendar = found[0]
    assert calendar["type"] == "rifiuti"
    assert calendar["name"] == "Ritiri a mano"
    assert calendar["source"] == "manual"
    assert calendar["color"] and calendar["icon"]
    assert calendar["error"] is None
