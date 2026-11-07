"""Timing tests: restart catch-up, Europe/Berlin DST changes, and all-day day-before reminders."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.family_hub.const import (
    CONF_ALL_DAY_REMINDER,
    CONF_FAMILY_NAME,
    CONF_FIRST_WEEKDAY,
    CONF_LANGUAGE,
    CONF_PHONE_NOTIFY,
    DOMAIN,
    OPT_CATEGORIES,
    OPT_PERSONS,
    OPT_REMINDERS,
)

SOFIA = {
    "id": "sofia",
    "name": "Sofia",
    "color": "#FF8800",
    "role": "child",
    CONF_PHONE_NOTIFY: "mobile_app_sofia",
}


def local(hour: int, minute: int = 0, day: int = 10, month: int = 11) -> datetime:
    """A wall-clock time in the instance time zone (set per test)."""
    return datetime(2026, month, day, hour, minute, tzinfo=dt_util.get_default_time_zone())


async def _setup(
    hass: HomeAssistant,
    persons: list[dict[str, Any]] | None = None,
    reminders: dict[str, Any] | None = None,
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
        options={
            OPT_PERSONS: persons if persons is not None else [SOFIA],
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
        DOMAIN,
        "add_event",
        {"category": "famiglia", **data},
        blocking=True,
    )


async def _tick(hass: HomeAssistant, freezer: Any, when: datetime) -> None:
    freezer.move_to(when)
    async_fire_time_changed(hass, when)
    await hass.async_block_till_done()


# ----- restart catch-up ---------------------------------------------------


async def test_restart_sends_a_reminder_that_was_due_less_than_ten_minutes_ago(
    hass: HomeAssistant, freezer: Any
) -> None:
    freezer.move_to(local(10))
    entry = await _setup(hass)
    notify = async_mock_service(hass, "notify", "mobile_app_sofia")
    await _add(hass, summary="Dentista", start="2026-11-10 15:00:00", persons=["sofia"])

    # The 14:30 reminder was due 8 minutes ago: the restart sends it once.
    freezer.move_to(local(14, 38))
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(notify) == 1

    # Another restart does not send it again: it is marked as sent.
    freezer.move_to(local(14, 39))
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(notify) == 1

    # The 14:50 reminder is still scheduled after the restarts.
    await _tick(hass, freezer, local(14, 50))
    assert len(notify) == 2


async def test_restart_drops_a_reminder_older_than_ten_minutes(
    hass: HomeAssistant, freezer: Any
) -> None:
    freezer.move_to(local(10))
    entry = await _setup(hass)
    notify = async_mock_service(hass, "notify", "mobile_app_sofia")
    await _add(hass, summary="Dentista", start="2026-11-10 15:00:00", persons=["sofia"])

    # The 14:30 reminder was due 15 minutes ago: it is not sent at restart.
    freezer.move_to(local(14, 45))
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert notify == []

    # The 14:50 reminder is still sent on time.
    await _tick(hass, freezer, local(14, 50))
    assert len(notify) == 1


# ----- Europe/Berlin and the clock change --------------------------------


async def test_berlin_spring_change_reminder_arrives_at_local_0830(
    hass: HomeAssistant, freezer: Any
) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime(2026, 3, 29, 8, 0, tzinfo=dt_util.get_default_time_zone()))
    await _setup(hass)
    notify = async_mock_service(hass, "notify", "mobile_app_sofia")
    await _add(hass, summary="Dentista", start="2026-03-29 09:00:00", persons=["sofia"])

    berlin = dt_util.get_default_time_zone()
    await _tick(hass, freezer, datetime(2026, 3, 29, 8, 29, tzinfo=berlin))
    assert notify == []
    await _tick(hass, freezer, datetime(2026, 3, 29, 8, 30, tzinfo=berlin))
    assert len(notify) == 1
    assert notify[0].data["message"].startswith("09:00")


async def test_berlin_spring_change_between_event_and_reminder(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Event 04:00 CEST, reminder 90 minutes before: 01:30 CET, before the clock jump at 03:00."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime(2026, 3, 29, 0, 0, tzinfo=dt_util.UTC))
    # 01:30 local is inside the default quiet hours, so switch them off for this test.
    await _setup(hass, reminders={"offsets": [90], "quiet_start": "", "quiet_end": ""})
    notify = async_mock_service(hass, "notify", "mobile_app_sofia")
    await _add(hass, summary="Gita", start="2026-03-29 04:00:00", persons=["sofia"])

    await _tick(hass, freezer, datetime(2026, 3, 29, 0, 29, tzinfo=dt_util.UTC))
    assert notify == []
    await _tick(hass, freezer, datetime(2026, 3, 29, 0, 30, tzinfo=dt_util.UTC))
    assert len(notify) == 1


async def test_berlin_autumn_change_reminder_arrives_at_local_1100(
    hass: HomeAssistant, freezer: Any
) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime(2026, 10, 25, 8, 0, tzinfo=dt_util.UTC))
    await _setup(hass, reminders={"offsets": [60]})
    notify = async_mock_service(hass, "notify", "mobile_app_sofia")
    await _add(hass, summary="Visita", start="2026-10-25 12:00:00", persons=["sofia"])

    # 12:00 CET is 11:00 UTC; the one-hour reminder is 11:00 CET = 10:00 UTC.
    await _tick(hass, freezer, datetime(2026, 10, 25, 9, 59, tzinfo=dt_util.UTC))
    assert notify == []
    await _tick(hass, freezer, datetime(2026, 10, 25, 10, 0, tzinfo=dt_util.UTC))
    assert len(notify) == 1


async def test_berlin_autumn_change_between_event_and_reminder(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Event 03:30 CET (after the jump), reminder 2 hours before: 02:30 CEST, before the jump."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(datetime(2026, 10, 24, 22, 0, tzinfo=dt_util.UTC))
    # 02:30 local is inside the default quiet hours, so switch them off for this test.
    await _setup(hass, reminders={"offsets": [120], "quiet_start": "", "quiet_end": ""})
    notify = async_mock_service(hass, "notify", "mobile_app_sofia")
    await _add(hass, summary="Treno", start="2026-10-25 03:30:00", persons=["sofia"])

    await _tick(hass, freezer, datetime(2026, 10, 25, 0, 29, tzinfo=dt_util.UTC))
    assert notify == []
    await _tick(hass, freezer, datetime(2026, 10, 25, 0, 30, tzinfo=dt_util.UTC))
    assert len(notify) == 1
    assert notify[0].data["message"].startswith("03:30")


# ----- all-day events: the day before ------------------------------------


async def test_all_day_event_reminder_the_day_before_at_family_time(
    hass: HomeAssistant, freezer: Any
) -> None:
    freezer.move_to(local(10))
    await _setup(hass)
    notify = async_mock_service(hass, "notify", "mobile_app_sofia")
    await _add(hass, summary="Gita", start="2026-11-11", persons=["sofia"])

    await _tick(hass, freezer, local(18, 59, day=10))
    assert notify == []
    await _tick(hass, freezer, local(19, 0, day=10))
    assert len(notify) == 1
    assert notify[0].data["message"] == "Gita · domani"


async def test_all_day_reminder_time_can_be_set_per_person(
    hass: HomeAssistant, freezer: Any
) -> None:
    freezer.move_to(local(10))
    await _setup(hass, persons=[{**SOFIA, CONF_ALL_DAY_REMINDER: "18:00"}])
    notify = async_mock_service(hass, "notify", "mobile_app_sofia")
    await _add(hass, summary="Gita", start="2026-11-11", persons=["sofia"])

    await _tick(hass, freezer, local(17, 59, day=10))
    assert notify == []
    await _tick(hass, freezer, local(18, 0, day=10))
    assert len(notify) == 1


async def test_all_day_reminder_time_can_be_set_per_event(
    hass: HomeAssistant, freezer: Any
) -> None:
    freezer.move_to(local(10))
    await _setup(hass)
    notify = async_mock_service(hass, "notify", "mobile_app_sofia")
    await _add(
        hass,
        summary="Gita",
        start="2026-11-11",
        persons=["sofia"],
        all_day_reminder="20:00",
    )

    # The event's own time wins over the family's 19:00. Only the Gita reminder counts here:
    # the evening summary at 20:00 goes to the same phone and is not the reminder.
    def gita() -> list[Any]:
        return [call for call in notify if call.data["title"] == "Promemoria"]

    await _tick(hass, freezer, local(19, 0, day=10))
    assert gita() == []
    await _tick(hass, freezer, local(20, 0, day=10))
    assert len(gita()) == 1
