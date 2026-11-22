"""Chosen dates (0.11.0b1): one event on dates picked by hand, each with its own start and end.

The dates are one series with no repeat rule: one record per date, all written already, so the
rule extension never touches them. "Solo questo" changes or deletes one date; "Tutti" changes the
fields of every date, and replaces the dates (their times included) only through "dates"."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import probatio as vol
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_recurring import _events, _store

from custom_components.family_hub.calendar import MAX_CHOSEN_DATES, extend_series
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
MORNING = {"start": "2026-11-14 10:00:00", "end": "2026-11-14 11:00:00"}
EVENING = {"start": "2026-12-22 18:00:00", "end": "2026-12-22 19:30:00"}


async def _setup(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Europe/Berlin")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
        options={
            OPT_PERSONS: [{"id": "mamma", "name": "Mamma", "color": "#EF4444"}],
            OPT_CATEGORIES: [{"id": CATEGORY, "name": "Famiglia", "color": "#3B82F6"}],
            CONF_LANGUAGE: "it",
            OPT_REMINDERS: {"channels": ["tablet"], "quiet_start": None, "quiet_end": None},
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _create(hass: HomeAssistant, dates: list[dict[str, str]], **extra: Any) -> None:
    data = {
        "category": CATEGORY,
        "summary": "Recita di Natale",
        "start": dates[0]["start"],
        "persons": ["mamma"],
        "dates": dates,
        **extra,
    }
    await hass.services.async_call(DOMAIN, "add_event", data, blocking=True)
    await hass.async_block_till_done()


async def _update(hass: HomeAssistant, uid: str, scope: str | None, **data: Any) -> None:
    payload: dict[str, Any] = {"uid": uid, **data}
    if scope is not None:
        payload["recurrence_range"] = scope
    await hass.services.async_call(DOMAIN, "update_event", payload, blocking=True)
    await hass.async_block_till_done()


def _chosen(hass: HomeAssistant) -> list[dict[str, Any]]:
    return sorted(
        (r for r in _store(hass).events.values() if r.get("chosen")),
        key=lambda r: r["start"],
    )


async def test_three_dates_are_one_series_with_their_own_times(hass: HomeAssistant) -> None:
    await _setup(hass)
    third = {"start": "2027-01-06 09:00:00", "end": "2027-01-06 09:30:00"}
    await _create(hass, [MORNING, EVENING, third])
    records = _chosen(hass)
    assert [r["start"] for r in records] == [
        "2026-11-14T10:00:00+01:00",
        "2026-12-22T18:00:00+01:00",
        "2027-01-06T09:00:00+01:00",
    ]
    assert [r["end"] for r in records][1] == "2026-12-22T19:30:00+01:00"
    assert len({r["series"] for r in records}) == 1
    assert all(r["rrule"] == "" and r["complete"] and r["written"] == "" for r in records)


async def test_a_past_date_is_allowed_and_repeated_dates_are_dropped(hass: HomeAssistant) -> None:
    await _setup(hass)
    past = {"start": "2026-03-01 08:00:00", "end": "2026-03-01 09:00:00"}
    await _create(hass, [MORNING, past, MORNING])
    assert [r["start"][:10] for r in _chosen(hass)] == ["2026-03-01", "2026-11-14"]


async def test_more_than_the_limit_is_refused(hass: HomeAssistant) -> None:
    await _setup(hass)
    dates = [
        {
            "start": (datetime(2027, 1, 1, 10) + timedelta(days=i)).strftime("%Y-%m-%d %H:%M:%S"),
            "end": (datetime(2027, 1, 1, 11) + timedelta(days=i)).strftime("%Y-%m-%d %H:%M:%S"),
        }
        for i in range(MAX_CHOSEN_DATES + 1)
    ]
    with pytest.raises(vol.Invalid):
        await _create(hass, dates)
    assert _chosen(hass) == []


async def test_dates_with_a_repeat_rule_are_refused(hass: HomeAssistant) -> None:
    await _setup(hass)
    with pytest.raises(ServiceValidationError, match="dates_no_rrule"):
        await _create(hass, [MORNING, EVENING], rrule="FREQ=WEEKLY;COUNT=3")
    assert _chosen(hass) == []


async def test_an_end_before_its_start_is_refused_on_its_row(hass: HomeAssistant) -> None:
    await _setup(hass)
    backwards = {"start": "2026-12-22 18:00:00", "end": "2026-12-22 17:00:00"}
    with pytest.raises(ServiceValidationError, match="end must be after start"):
        await _create(hass, [MORNING, backwards])
    assert _chosen(hass) == []


async def test_this_date_only_changes_that_date(hass: HomeAssistant) -> None:
    await _setup(hass)
    await _create(hass, [MORNING, EVENING])
    first = _chosen(hass)[0]
    await _update(hass, first["uid"], None, summary="Prova generale")
    assert [r["summary"] for r in _chosen(hass)] == ["Prova generale", "Recita di Natale"]


async def test_all_changes_the_title_and_keeps_every_time(hass: HomeAssistant) -> None:
    await _setup(hass)
    await _create(hass, [MORNING, EVENING])
    before = [(r["start"], r["end"]) for r in _chosen(hass)]
    await _update(hass, _chosen(hass)[0]["uid"], "ALL", summary="Concerto")
    records = _chosen(hass)
    assert [r["summary"] for r in records] == ["Concerto", "Concerto"]
    assert [(r["start"], r["end"]) for r in records] == before


async def test_all_adds_and_removes_dates_and_keeps_the_times_of_each(hass: HomeAssistant) -> None:
    await _setup(hass)
    await _create(hass, [MORNING, EVENING])
    keep = _chosen(hass)[1]
    new = {"start": "2026-12-23 10:00:00", "end": "2026-12-23 12:00:00"}
    changed = {"start": EVENING["start"], "end": "2026-12-22 20:00:00"}
    await _update(hass, keep["uid"], "ALL", dates=[changed, new])
    starts = {r["start"]: r["end"] for r in _chosen(hass)}
    assert starts == {
        "2026-12-22T18:00:00+01:00": "2026-12-22T20:00:00+01:00",
        "2026-12-23T10:00:00+01:00": "2026-12-23T12:00:00+01:00",
    }
    assert len({r["series"] for r in _chosen(hass)}) == 1


async def test_all_with_a_time_in_the_fields_is_refused(hass: HomeAssistant) -> None:
    await _setup(hass)
    await _create(hass, [MORNING, EVENING])
    uid = _chosen(hass)[0]["uid"]
    with pytest.raises(ServiceValidationError, match="dates_times_per_date"):
        await _update(hass, uid, "ALL", start="2026-11-15 10:00:00", end="2026-11-15 11:00:00")


async def test_a_repeat_rule_on_all_is_refused_for_chosen_dates(hass: HomeAssistant) -> None:
    await _setup(hass)
    await _create(hass, [MORNING, EVENING])
    uid = _chosen(hass)[0]["uid"]
    with pytest.raises(ServiceValidationError, match="dates_no_rrule"):
        await _update(hass, uid, "ALL", rrule="FREQ=DAILY;COUNT=2")
    assert len(_chosen(hass)) == 2


async def test_dates_on_an_ordinary_event_are_refused(hass: HomeAssistant) -> None:
    await _setup(hass)
    await hass.services.async_call(
        DOMAIN,
        "add_event",
        {"category": CATEGORY, "summary": "Visita", **MORNING},
        blocking=True,
    )
    await hass.async_block_till_done()
    uid = next(iter(_store(hass).events))
    with pytest.raises(ServiceValidationError, match="dates_only_for_chosen_dates"):
        await _update(hass, uid, "ALL", dates=[EVENING])


async def test_this_date_is_deleted_and_all_deletes_the_rest(hass: HomeAssistant) -> None:
    await _setup(hass)
    await _create(hass, [MORNING, EVENING])
    await hass.services.async_call(
        DOMAIN, "delete_event", {"uid": _chosen(hass)[0]["uid"]}, blocking=True
    )
    await hass.async_block_till_done()
    assert [r["start"] for r in _chosen(hass)] == ["2026-12-22T18:00:00+01:00"]
    await hass.services.async_call(
        DOMAIN,
        "delete_event",
        {"uid": _chosen(hass)[0]["uid"], "recurrence_range": "ALL"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert _chosen(hass) == []


async def test_each_date_has_its_own_reminder(hass: HomeAssistant) -> None:
    await _setup(hass)
    await _create(hass, [MORNING, EVENING])
    reminders = hass.config_entries.async_entries(DOMAIN)[0].runtime_data.reminders
    for record in _chosen(hass):
        moments = [moment for moment, _ in reminders._record_moments(record)]
        assert moments, "every chosen date has reminders"
        assert min(moments) < datetime.fromisoformat(record["start"])


async def test_the_yearly_extension_leaves_chosen_dates_alone(hass: HomeAssistant) -> None:
    await _setup(hass)
    await _create(hass, [MORNING, EVENING])
    before = sorted(_store(hass).events)
    changed = extend_series(_store(hass), dt_util.now() + timedelta(days=900))
    assert changed is False
    assert sorted(_store(hass).events) == before


async def test_each_date_shows_in_the_calendar_in_its_own_week(hass: HomeAssistant) -> None:
    await _setup(hass)
    await _create(hass, [MORNING, EVENING])
    events = await _events(hass)
    assert [e["start"][:10] for e in events] == ["2026-11-14", "2026-12-22"]
    assert all(e["summary"] == "Recita di Natale" for e in events)
