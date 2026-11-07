"""Tests for reminders: timers, quiet hours, snoozes, phone buttons, speakers and summaries."""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.family_hub.const import (
    ACTION_EVENT,
    CONF_FAMILY_NAME,
    CONF_FIRST_WEEKDAY,
    CONF_LANGUAGE,
    CONF_PHONE_NOTIFY,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_SPEAKER,
    DOMAIN,
    OPT_CATEGORIES,
    OPT_PERSONS,
    OPT_REMINDERS,
)
from custom_components.family_hub.reminders import (
    in_quiet_hours,
    parse_hhmm,
    reminder_times,
)

CALENDAR = "calendar.family_hub_famiglia"


def local(hour: int, minute: int = 0, day: int = 10) -> datetime:
    """A moment on 2026-11-<day> in the Home Assistant time zone of the test instance."""
    return datetime(2026, 11, day, hour, minute, tzinfo=dt_util.get_default_time_zone())


async def _setup(
    hass: HomeAssistant,
    *,
    persons: list[dict[str, Any]] | None = None,
    reminders: dict[str, Any] | None = None,
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
        options={
            OPT_PERSONS: persons
            if persons is not None
            else [
                {
                    "id": "sofia",
                    "name": "Sofia",
                    "color": "#FF8800",
                    "role": "child",
                    CONF_PHONE_NOTIFY: "mobile_app_sofia",
                }
            ],
            OPT_CATEGORIES: [{"id": "famiglia", "name": "Famiglia", "color": "#3B82F6"}],
            OPT_REMINDERS: reminders or {},
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _add(hass: HomeAssistant, **data: Any) -> None:
    await hass.services.async_call(
        DOMAIN, "add_event", {"category": "famiglia", **data}, blocking=True
    )


def _only_uid(entry: MockConfigEntry) -> str:
    (uid,) = entry.runtime_data.store.events
    return uid


async def _tick(hass: HomeAssistant, freezer: Any, when: datetime) -> None:
    """Move the clock to ``when`` and fire the timers due by then.

    The clock must move too: quiet hours and summaries read the current time.
    """
    freezer.move_to(when)
    async_fire_time_changed(hass, when)
    await hass.async_block_till_done()


# ----- pure functions -----------------------------------------------------


def test_parse_hhmm() -> None:
    assert parse_hhmm("07:30") == time(7, 30)
    assert parse_hhmm(" 22:00 ") == time(22, 0)
    assert parse_hhmm("") is None
    assert parse_hhmm(None) is None
    for bad in ("7:30", "25:00", "12:60", "noon"):
        with pytest.raises(ValueError):
            parse_hhmm(bad)


def test_quiet_hours_cross_midnight() -> None:
    start, end = time(22, 0), time(7, 0)
    assert in_quiet_hours(time(23, 0), start, end)
    assert in_quiet_hours(time(6, 59), start, end)
    assert not in_quiet_hours(time(7, 0), start, end)
    assert not in_quiet_hours(time(12, 0), start, end)


def test_quiet_hours_same_day_window() -> None:
    assert in_quiet_hours(time(14, 0), time(14, 0), time(16, 0))
    assert not in_quiet_hours(time(16, 0), time(14, 0), time(16, 0))


def test_quiet_hours_unset_or_empty_window() -> None:
    assert not in_quiet_hours(time(23, 0), None, None)
    assert not in_quiet_hours(time(23, 0), time(9, 0), time(9, 0))


def test_reminder_times_keep_only_future_moments_in_order() -> None:
    start = local(15, 0)
    moments = reminder_times(start, [60, 10, 30], local(14, 0))
    assert moments == [local(14, 30), local(14, 50)]


# ----- scheduling and delivery --------------------------------------------


async def test_reminders_fire_at_each_offset_on_phone_and_tablet(
    hass: HomeAssistant, freezer: Any
) -> None:
    freezer.move_to(local(10, 0))
    entry = await _setup(hass)
    notify = async_mock_service(hass, "notify", "mobile_app_sofia")
    tablet = async_mock_service(hass, "persistent_notification", "create")
    await _add(hass, summary="Dentista", start="2026-11-10 15:00:00", persons=["sofia"])

    await _tick(hass, freezer, local(14, 30))
    assert len(notify) == 1
    assert notify[0].data["title"] == "Promemoria"
    assert "Dentista" in notify[0].data["message"]
    actions = [a["action"] for a in notify[0].data["data"]["actions"]]
    uid = _only_uid(entry)
    assert f"FH_DONE_{uid}" in actions
    assert len(tablet) == 1

    await _tick(hass, freezer, local(14, 50))
    assert len(notify) == 2


async def test_event_offsets_override_the_family_default(hass: HomeAssistant, freezer: Any) -> None:
    freezer.move_to(local(10, 0))
    await _setup(hass)
    notify = async_mock_service(hass, "notify", "mobile_app_sofia")
    await _add(
        hass,
        summary="Visita",
        start="2026-11-10 15:00:00",
        persons=["sofia"],
        reminder_offsets=[5],
    )
    await _tick(hass, freezer, local(14, 30))
    assert notify == []
    await _tick(hass, freezer, local(14, 55))
    assert len(notify) == 1


async def test_quiet_hours_silence_the_person_and_the_tablet(
    hass: HomeAssistant, freezer: Any
) -> None:
    freezer.move_to(local(10, 0))
    persons = [
        {
            "id": "sofia",
            "name": "Sofia",
            "color": "#FF8800",
            "role": "child",
            CONF_PHONE_NOTIFY: "mobile_app_sofia",
            CONF_QUIET_START: "14:00",
            CONF_QUIET_END: "16:00",
        }
    ]
    await _setup(hass, persons=persons)
    notify = async_mock_service(hass, "notify", "mobile_app_sofia")
    tablet = async_mock_service(hass, "persistent_notification", "create")
    await _add(hass, summary="Dentista", start="2026-11-10 15:00:00", persons=["sofia"])

    await _tick(hass, freezer, local(14, 30))
    assert notify == []
    assert tablet == []


async def test_speaker_is_used_when_tts_is_configured(hass: HomeAssistant, freezer: Any) -> None:
    freezer.move_to(local(10, 0))
    persons = [
        {
            "id": "sofia",
            "name": "Sofia",
            "color": "#FF8800",
            "role": "child",
            CONF_SPEAKER: "media_player.cucina",
        }
    ]
    await _setup(
        hass, persons=persons, reminders={"channels": ["speaker"], "tts_entity": "tts.test"}
    )
    speak = async_mock_service(hass, "tts", "speak")
    await _add(hass, summary="Dentista", start="2026-11-10 15:00:00", persons=["sofia"])

    await _tick(hass, freezer, local(14, 30))
    assert len(speak) == 1
    assert speak[0].data["media_player_entity_id"] == "media_player.cucina"
    assert speak[0].data["entity_id"] == "tts.test"


async def test_stop_reminder_cancels_pending_reminders(hass: HomeAssistant, freezer: Any) -> None:
    freezer.move_to(local(10, 0))
    entry = await _setup(hass)
    notify = async_mock_service(hass, "notify", "mobile_app_sofia")
    await _add(hass, summary="Dentista", start="2026-11-10 15:00:00", persons=["sofia"])

    await hass.services.async_call(
        DOMAIN, "stop_reminder", {"uid": _only_uid(entry)}, blocking=True
    )
    await _tick(hass, freezer, local(14, 30))
    await _tick(hass, freezer, local(14, 50))
    assert notify == []


async def test_snooze_reminder_adds_a_later_reminder(hass: HomeAssistant, freezer: Any) -> None:
    freezer.move_to(local(10, 0))
    entry = await _setup(hass)
    notify = async_mock_service(hass, "notify", "mobile_app_sofia")
    await _add(hass, summary="Dentista", start="2026-11-10 15:00:00", persons=["sofia"])

    await hass.services.async_call(
        DOMAIN,
        "snooze_reminder",
        {"uid": _only_uid(entry), "minutes": 60},
        blocking=True,
    )
    await _tick(hass, freezer, local(11, 0))
    assert len(notify) == 1
    # The original reminder is still scheduled.
    await _tick(hass, freezer, local(14, 30))
    assert len(notify) == 2


async def test_phone_snooze_button_schedules_a_snooze(hass: HomeAssistant, freezer: Any) -> None:
    freezer.move_to(local(10, 0))
    entry = await _setup(hass)
    notify = async_mock_service(hass, "notify", "mobile_app_sofia")
    await _add(hass, summary="Dentista", start="2026-11-10 15:00:00", persons=["sofia"])
    uid = _only_uid(entry)

    hass.bus.async_fire(ACTION_EVENT, {"action": f"FH_SNOOZE_10_{uid}"})
    await hass.async_block_till_done()
    await _tick(hass, freezer, local(10, 10))
    assert len(notify) == 1


async def test_phone_done_button_stops_the_event(hass: HomeAssistant, freezer: Any) -> None:
    freezer.move_to(local(10, 0))
    entry = await _setup(hass)
    notify = async_mock_service(hass, "notify", "mobile_app_sofia")
    await _add(hass, summary="Dentista", start="2026-11-10 15:00:00", persons=["sofia"])
    uid = _only_uid(entry)

    hass.bus.async_fire(ACTION_EVENT, {"action": f"FH_DONE_{uid}"})
    await hass.async_block_till_done()
    assert entry.runtime_data.store.events[uid]["reminders_off"] is True
    await _tick(hass, freezer, local(14, 30))
    assert notify == []


async def test_morning_summary_lists_todays_events(hass: HomeAssistant, freezer: Any) -> None:
    freezer.move_to(local(6, 0))
    await _setup(hass)
    tablet = async_mock_service(hass, "persistent_notification", "create")
    await _add(hass, summary="Dentista", start="2026-11-10 15:00:00", persons=["sofia"])
    await _add(hass, category="famiglia", summary="Gita", start="2026-11-10")
    await _add(hass, summary="Domani", start="2026-11-11 09:00:00")

    await _tick(hass, freezer, local(7, 0))
    assert len(tablet) == 1
    message = tablet[0].data["message"]
    assert "15:00  Dentista (Sofia)" in message
    assert "Gita" in message
    assert "Domani" not in message


async def test_evening_summary_lists_tomorrow(hass: HomeAssistant, freezer: Any) -> None:
    freezer.move_to(local(19, 0))
    await _setup(hass)
    tablet = async_mock_service(hass, "persistent_notification", "create")
    await _add(hass, summary="Domani", start="2026-11-11 09:00:00")
    await _add(hass, summary="Oggi", start="2026-11-10 09:00:00")

    await _tick(hass, freezer, local(20, 0))
    assert len(tablet) == 1
    message = tablet[0].data["message"]
    assert "Domani" in message
    assert "Oggi" not in message


# ----- options flow ------------------------------------------------------


async def test_reminder_settings_flow_saves_options(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
        options={OPT_PERSONS: [], OPT_CATEGORIES: []},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "reminders"}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "offsets": "30, 10",
            "channels": ["phone", "tablet"],
            "quiet_start": "23:00",
            "quiet_end": "06:30",
            "snooze_minutes": 15,
            "morning_summary": "07:15",
            "evening_summary": "",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    saved = entry.options[OPT_REMINDERS]
    assert saved["offsets"] == [30, 10]
    assert saved["channels"] == ["phone", "tablet"]
    assert saved["morning_summary"] == "07:15"
    assert saved["evening_summary"] is None


async def test_reminder_settings_flow_rejects_bad_values(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
        options={OPT_PERSONS: [], OPT_CATEGORIES: []},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "reminders"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "offsets": "trenta",
            "channels": ["phone"],
            "quiet_start": "25:00",
            "quiet_end": "07:00",
            "snooze_minutes": 10,
            "morning_summary": "07:00",
            "evening_summary": "20:00",
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"offsets": "invalid_offsets", "quiet_start": "invalid_time"}
