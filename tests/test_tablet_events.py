"""What the wall-tablet add-on relies on: bus events for reminder popups and the category id."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.family_hub.const import (
    CONF_FAMILY_NAME,
    CONF_FIRST_WEEKDAY,
    CONF_LANGUAGE,
    DOMAIN,
    OPT_CATEGORIES,
    OPT_PERSONS,
)

CAL = "calendar.family_hub_famiglia"


async def _setup(hass: HomeAssistant, channels: list[str]) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
        options={
            OPT_PERSONS: [{"id": "sofia", "name": "Sofia", "color": "#FF8800", "role": "child"}],
            OPT_CATEGORIES: [{"id": "famiglia", "name": "Famiglia", "color": "#3B82F6"}],
            # No quiet hours, so the tablet is never silenced in these tests.
            "reminders": {
                "offsets": [30],
                "channels": channels,
                "quiet_start": "",
                "quiet_end": "",
                "snooze_minutes": 10,
                "tts_entity": None,
                "morning_summary": None,
                "evening_summary": None,
                "all_day_reminder": "19:00",
            },
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _add_dentist(hass: HomeAssistant) -> None:
    await hass.services.async_call(
        DOMAIN,
        "add_event",
        {
            "category": "famiglia",
            "summary": "Dentista",
            "start": "2027-01-10 15:00:00",
            "end": "2027-01-10 16:00:00",
            "persons": ["sofia"],
        },
        blocking=True,
    )


async def test_tablet_reminder_is_announced_on_the_bus(hass: HomeAssistant) -> None:
    entry = await _setup(hass, ["tablet"])
    await _add_dentist(hass)
    (uid,) = entry.runtime_data.store.events
    announced = async_capture_events(hass, "family_hub_reminder")

    await entry.runtime_data.reminders.async_fire(
        uid, dt_util.parse_datetime("2027-01-10T14:30:00+01:00")
    )
    await hass.async_block_till_done()

    (event,) = announced
    data: dict[str, Any] = event.data
    assert data["uid"] == uid
    assert data["title"] == "Promemoria"
    assert data["message"] == "15:00 · Dentista"
    assert data["notification_id"] == f"family_hub_{uid}"


async def test_no_tablet_channel_means_no_popup_event(hass: HomeAssistant) -> None:
    entry = await _setup(hass, ["phone"])
    await _add_dentist(hass)
    (uid,) = entry.runtime_data.store.events
    announced = async_capture_events(hass, "family_hub_reminder")

    await entry.runtime_data.reminders.async_fire(
        uid, dt_util.parse_datetime("2027-01-10T14:30:00+01:00")
    )
    await hass.async_block_till_done()

    assert announced == []


async def test_dismissed_reminder_closes_popups_everywhere(hass: HomeAssistant) -> None:
    entry = await _setup(hass, ["tablet"])
    await _add_dentist(hass)
    (uid,) = entry.runtime_data.store.events
    closed = async_capture_events(hass, "family_hub_reminder_closed")

    await entry.runtime_data.reminders.async_dismiss(uid)
    await hass.async_block_till_done()

    (event,) = closed
    assert event.data["uid"] == uid


async def test_stopping_an_event_closes_its_popup(hass: HomeAssistant) -> None:
    entry = await _setup(hass, ["tablet"])
    await _add_dentist(hass)
    (uid,) = entry.runtime_data.store.events
    closed = async_capture_events(hass, "family_hub_reminder_closed")

    await hass.services.async_call(DOMAIN, "stop_reminder", {"uid": uid}, blocking=True)
    await hass.async_block_till_done()

    assert [event.data["uid"] for event in closed] == [uid]


async def test_calendar_state_carries_the_category_id(hass: HomeAssistant) -> None:
    await _setup(hass, ["tablet"])
    state = hass.states.get(CAL)
    assert state is not None
    assert state.attributes["category_id"] == "famiglia"


async def test_calendar_state_lists_persons_with_roles_and_user_links(hass: HomeAssistant) -> None:
    await _setup(hass, ["tablet"])
    state = hass.states.get(CAL)
    assert state is not None
    assert state.attributes["persons"] == [
        {"id": "sofia", "name": "Sofia", "role": "child", "ha_user_id": None, "color": "#FF8800"}
    ]


async def test_websocket_event_list_is_what_the_tablet_reads(
    hass: HomeAssistant, hass_ws_client: Any
) -> None:
    """The tablet add-on reads events with calendar/event/subscribe: check the fields it needs."""
    entry = await _setup(hass, ["tablet"])
    await _add_dentist(hass)
    (uid,) = entry.runtime_data.store.events
    client = await hass_ws_client(hass)
    await client.send_json(
        {
            "id": 1,
            "type": "calendar/event/subscribe",
            "entity_id": CAL,
            "start": "2027-01-01 00:00:00",
            "end": "2027-02-01 00:00:00",
        }
    )
    assert (await client.receive_json())["success"] is True
    message = await client.receive_json()
    (event,) = message["event"]["events"]
    assert event["person_ids"] == "sofia"
    assert event["record_id"] == uid
    assert event["summary"] == "Dentista"
