"""Tests for the Family Hub actions and the calendar entities behind them."""

from __future__ import annotations

from typing import Any

import probatio as vol
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.family_hub.const import (
    CONF_FAMILY_NAME,
    CONF_FIRST_WEEKDAY,
    CONF_LANGUAGE,
    DOMAIN,
    OPT_CATEGORIES,
    OPT_PERSONS,
)

CALENDAR = "calendar.family_hub_famiglia"
WINDOW = {
    "start_date_time": "2026-11-01 00:00:00",
    "end_date_time": "2026-12-01 00:00:00",
}


@pytest.fixture
async def family(hass: HomeAssistant) -> MockConfigEntry:
    """A loaded Family Hub entry with one person and two categories."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
        options={
            OPT_PERSONS: [{"id": "sofia", "name": "Sofia", "color": "#FF8800", "role": "child"}],
            OPT_CATEGORIES: [
                {"id": "famiglia", "name": "Famiglia", "color": "#3B82F6"},
                {"id": "scuola", "name": "Scuola", "color": "#10B981"},
            ],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _events(hass: HomeAssistant, entity_id: str = CALENDAR) -> list[dict[str, Any]]:
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {"entity_id": entity_id, **WINDOW},
        blocking=True,
        return_response=True,
    )
    return response[entity_id]["events"]


async def _add(hass: HomeAssistant, **data: Any) -> None:
    await hass.services.async_call(
        DOMAIN, "add_event", {"category": "famiglia", **data}, blocking=True
    )


def _only_uid(family: MockConfigEntry) -> str:
    """calendar.get_events does not return uids, so read the single stored event's uid."""
    (uid,) = family.runtime_data.store.events
    return uid


async def test_add_event_with_end(hass: HomeAssistant, family: MockConfigEntry) -> None:
    await _add(
        hass,
        summary="Dentista",
        start="2026-11-10 15:00:00",
        end="2026-11-10 16:30:00",
        persons=["sofia"],
    )
    events = await _events(hass)
    assert len(events) == 1
    assert events[0]["summary"] == "Dentista"
    assert events[0]["start"].startswith("2026-11-10T15:00:00")
    assert events[0]["end"].startswith("2026-11-10T16:30:00")


async def test_add_event_defaults_end_to_one_hour(
    hass: HomeAssistant, family: MockConfigEntry
) -> None:
    await _add(hass, summary="Riunione", start="2026-11-11 09:00:00")
    (event,) = await _events(hass)
    assert event["end"].startswith("2026-11-11T10:00:00")


async def test_add_all_day_event(hass: HomeAssistant, family: MockConfigEntry) -> None:
    await _add(hass, summary="Gita", start="2026-11-12")
    (event,) = await _events(hass)
    assert event["start"].startswith("2026-11-12")
    assert event["end"].startswith("2026-11-13")


async def test_add_event_goes_to_its_category(hass: HomeAssistant, family: MockConfigEntry) -> None:
    await _add(hass, category="scuola", summary="Recita", start="2026-11-20 17:00:00")
    assert await _events(hass) == []
    assert len(await _events(hass, "calendar.family_hub_scuola")) == 1


async def test_add_event_rejects_unknown_category(
    hass: HomeAssistant, family: MockConfigEntry
) -> None:
    with pytest.raises(ServiceValidationError, match="Unknown category"):
        await _add(hass, category="nope", summary="X", start="2026-11-10 10:00:00")


async def test_add_event_rejects_unknown_person(
    hass: HomeAssistant, family: MockConfigEntry
) -> None:
    with pytest.raises(ServiceValidationError, match="Unknown person"):
        await _add(hass, summary="X", start="2026-11-10 10:00:00", persons=["marco"])


async def test_add_event_rejects_end_before_start(
    hass: HomeAssistant, family: MockConfigEntry
) -> None:
    with pytest.raises(ServiceValidationError, match="end must be after start"):
        await _add(hass, summary="X", start="2026-11-10 10:00:00", end="2026-11-10 09:00:00")


async def test_add_event_rejects_mixed_date_and_datetime(
    hass: HomeAssistant, family: MockConfigEntry
) -> None:
    with pytest.raises(ServiceValidationError, match="both be dates"):
        await _add(hass, summary="X", start="2026-11-10", end="2026-11-11 10:00:00")


async def test_add_event_rejects_bad_schema(hass: HomeAssistant, family: MockConfigEntry) -> None:
    with pytest.raises(vol.Invalid):
        await _add(hass, summary="", start="2026-11-10 10:00:00")


async def test_update_event_changes_only_given_fields(
    hass: HomeAssistant, family: MockConfigEntry
) -> None:
    await _add(hass, summary="Dentista", start="2026-11-10 15:00:00", location="Via Roma")
    (event,) = await _events(hass)

    await hass.services.async_call(
        DOMAIN,
        "update_event",
        {"uid": _only_uid(family), "summary": "Dentista (visita)"},
        blocking=True,
    )
    (updated,) = await _events(hass)
    assert updated["summary"] == "Dentista (visita)"
    assert updated["start"] == event["start"]
    assert updated["location"] == "Via Roma"


async def test_update_unknown_event_fails(hass: HomeAssistant, family: MockConfigEntry) -> None:
    with pytest.raises(ServiceValidationError, match="Unknown event"):
        await hass.services.async_call(
            DOMAIN, "update_event", {"uid": "missing", "summary": "X"}, blocking=True
        )


async def test_move_event_keeps_duration(hass: HomeAssistant, family: MockConfigEntry) -> None:
    await _add(hass, summary="Visita", start="2026-11-10 15:00:00", end="2026-11-10 16:00:00")
    (event,) = await _events(hass)

    await hass.services.async_call(
        DOMAIN,
        "move_event",
        {"uid": _only_uid(family), "start": "2026-11-11 09:00:00"},
        blocking=True,
    )
    (moved,) = await _events(hass)
    assert moved["start"].startswith("2026-11-11T09:00:00")
    assert moved["end"].startswith("2026-11-11T10:00:00")


async def test_move_event_with_explicit_end(hass: HomeAssistant, family: MockConfigEntry) -> None:
    await _add(hass, summary="Visita", start="2026-11-10 15:00:00")
    (event,) = await _events(hass)

    await hass.services.async_call(
        DOMAIN,
        "move_event",
        {
            "uid": _only_uid(family),
            "start": "2026-11-11 09:00:00",
            "end": "2026-11-11 12:00:00",
        },
        blocking=True,
    )
    (moved,) = await _events(hass)
    assert moved["end"].startswith("2026-11-11T12:00:00")


async def test_delete_event_removes_it(hass: HomeAssistant, family: MockConfigEntry) -> None:
    await _add(hass, summary="Da cancellare", start="2026-11-10 15:00:00")
    await _events(hass)

    await hass.services.async_call(
        DOMAIN, "delete_event", {"uid": _only_uid(family)}, blocking=True
    )
    assert await _events(hass) == []
    assert family.runtime_data.store.events == {}


async def test_delete_unknown_event_fails(hass: HomeAssistant, family: MockConfigEntry) -> None:
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "delete_event", {"uid": "nope"}, blocking=True)


async def test_events_survive_reload(hass: HomeAssistant, family: MockConfigEntry) -> None:
    await _add(hass, summary="Persistente", start="2026-11-10 15:00:00")
    assert await hass.config_entries.async_reload(family.entry_id)
    await hass.async_block_till_done()
    (event,) = await _events(hass)
    assert event["summary"] == "Persistente"


async def test_actions_are_registered_once(hass: HomeAssistant, family: MockConfigEntry) -> None:
    for action in ("add_event", "update_event", "delete_event", "move_event"):
        assert hass.services.has_service(DOMAIN, action)
