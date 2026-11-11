"""Repeating events: a weekly event on Tuesdays for four times is four occurrences.

A change to one occurrence reaches only that one; "this and the following" divides the series;
"all" deletes the series; the occurrences are written on past the horizon; and a reminder belongs
to one occurrence."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.family_hub import recurrence
from custom_components.family_hub.calendar import extend_series
from custom_components.family_hub.const import (
    CONF_FAMILY_NAME,
    CONF_FIRST_WEEKDAY,
    CONF_LANGUAGE,
    DOMAIN,
    OPT_CATEGORIES,
    OPT_PERSONS,
    OPT_REMINDERS,
)

CATEGORY = "famiglia"
ENTITY = "calendar.family_hub_famiglia"
WINDOW = {
    "start_date_time": "2026-11-01T00:00:00+01:00",
    "end_date_time": "2026-12-31T00:00:00+01:00",
}


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
        options={
            OPT_PERSONS: [],
            OPT_CATEGORIES: [{"id": CATEGORY, "name": "Famiglia", "color": "#3B82F6"}],
            CONF_LANGUAGE: "it",
            OPT_REMINDERS: {"channels": ["tablet"], "quiet_start": None, "quiet_end": None},
        },
    )


async def _setup(hass: HomeAssistant) -> Any:
    await hass.config.async_set_time_zone("Europe/Berlin")
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _create_weekly(hass: HomeAssistant, rule: str) -> None:
    await hass.services.async_call(
        DOMAIN,
        "add_event",
        {
            "category": CATEGORY,
            "summary": "Visita",
            "start": "2026-11-03T10:00:00+01:00",
            "end": "2026-11-03T11:00:00+01:00",
            "rrule": rule,
        },
        blocking=True,
    )
    await hass.async_block_till_done()


async def _events(hass: HomeAssistant) -> list[dict[str, Any]]:
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        WINDOW,
        target={"entity_id": ENTITY},
        blocking=True,
        return_response=True,
    )
    return sorted(response[ENTITY]["events"], key=lambda e: e["start"])


def _store(hass: HomeAssistant) -> Any:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    return entry.runtime_data.store


def _calendar(hass: HomeAssistant) -> Any:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    return entry.runtime_data.calendars[CATEGORY]


def _series_records(hass: HomeAssistant) -> list[dict[str, Any]]:
    return sorted(
        (r for r in _store(hass).events.values() if r.get("series")),
        key=lambda r: r["start"],
    )


async def test_a_weekly_event_on_tuesdays_for_four_times_is_four_occurrences(
    hass: HomeAssistant,
) -> None:
    await _setup(hass)
    await _create_weekly(hass, "FREQ=WEEKLY;BYDAY=TU;COUNT=4")
    starts = [e["start"][:10] for e in await _events(hass)]
    assert starts == ["2026-11-03", "2026-11-10", "2026-11-17", "2026-11-24"]
    assert len({r["series"] for r in _series_records(hass)}) == 1


async def test_a_change_to_one_occurrence_reaches_only_that_one(hass: HomeAssistant) -> None:
    await _setup(hass)
    await _create_weekly(hass, "FREQ=WEEKLY;BYDAY=TU;COUNT=4")
    second = _series_records(hass)[1]
    entity = _calendar(hass)
    await entity.async_update_event(second["uid"], {"summary": "Dentista"})
    names = [r["summary"] for r in _series_records(hass)]
    assert names == ["Visita", "Dentista", "Visita", "Visita"]


async def test_this_and_the_following_divides_the_series(hass: HomeAssistant) -> None:
    await _setup(hass)
    await _create_weekly(hass, "FREQ=WEEKLY;BYDAY=TU;COUNT=4")
    third = _series_records(hass)[2]
    entity = _calendar(hass)
    await entity.async_update_event(
        third["uid"], {"summary": "Nuovo orario"}, recurrence_range="THISANDFUTURE"
    )
    records = _series_records(hass)
    assert [r["summary"] for r in records] == ["Visita", "Visita", "Nuovo orario", "Nuovo orario"]
    earlier, later = records[0]["series"], records[2]["series"]
    assert earlier != later
    assert {r["series"] for r in records[:2]} == {earlier}
    assert {r["series"] for r in records[2:]} == {later}
    # The later series has the count that is left: two occurrences, not four.
    assert recurrence.describe(records[2]["rrule"])["count"] == 2


async def test_all_deletes_the_whole_series(hass: HomeAssistant) -> None:
    await _setup(hass)
    await _create_weekly(hass, "FREQ=WEEKLY;BYDAY=TU;COUNT=4")
    first = _series_records(hass)[0]
    entity = _calendar(hass)
    await entity.async_delete_event(first["uid"], recurrence_range="ALL")
    assert await _events(hass) == []


async def test_this_only_deletes_just_that_occurrence(hass: HomeAssistant) -> None:
    await _setup(hass)
    await _create_weekly(hass, "FREQ=WEEKLY;BYDAY=TU;COUNT=4")
    second = _series_records(hass)[1]
    entity = _calendar(hass)
    await entity.async_delete_event(second["uid"])
    starts = [e["start"][:10] for e in await _events(hass)]
    assert starts == ["2026-11-03", "2026-11-17", "2026-11-24"]


async def test_occurrences_are_written_on_past_the_horizon(hass: HomeAssistant) -> None:
    """A repeat with no end is written a year ahead, and the daily job keeps it going."""
    await _setup(hass)
    await _create_weekly(hass, "FREQ=WEEKLY;BYDAY=TU")
    store = _store(hass)
    now = dt_util.now()
    later = now + timedelta(days=500)
    assert extend_series(store, later) is True
    last = max(r["start"] for r in _series_records(hass))
    assert datetime.fromisoformat(last) > later - timedelta(days=60)


async def test_a_reminder_belongs_to_one_occurrence(hass: HomeAssistant) -> None:
    await _setup(hass)
    await _create_weekly(hass, "FREQ=WEEKLY;BYDAY=TU;COUNT=3")
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    reminders = entry.runtime_data.reminders
    second = _series_records(hass)[1]
    moments = [moment for moment, _ in reminders._record_moments(second)]
    start = datetime.fromisoformat(second["start"])
    assert moments, "the occurrence has reminders"
    assert min(moments) < start
