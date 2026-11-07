"""Tests for the Alexa announce channel and the optional browser_mod popup channel."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.family_hub.const import (
    CONF_ALEXA_NOTIFY,
    CONF_FAMILY_NAME,
    CONF_FIRST_WEEKDAY,
    CONF_LANGUAGE,
    CONF_PHONE_NOTIFY,
    CONF_SPEAKER,
    DOMAIN,
    OPT_CATEGORIES,
    OPT_PERSONS,
    OPT_REMINDERS,
)


def local(hour: int, minute: int = 0) -> datetime:
    """2026-11-10 at the given time in the instance time zone."""
    return datetime(2026, 11, 10, hour, minute, tzinfo=dt_util.get_default_time_zone())


async def _setup(
    hass: HomeAssistant,
    persons: list[dict[str, Any]],
    reminders: dict[str, Any] | None = None,
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
        options={
            OPT_PERSONS: persons,
            OPT_CATEGORIES: [{"id": "famiglia", "name": "Famiglia", "color": "#3B82F6"}],
            OPT_REMINDERS: reminders or {},
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _add(hass: HomeAssistant) -> None:
    await hass.services.async_call(
        DOMAIN,
        "add_event",
        {
            "category": "famiglia",
            "summary": "Dentista",
            "start": "2026-11-10 15:00:00",
            "persons": ["sofia"],
        },
        blocking=True,
    )


async def _tick(hass: HomeAssistant, freezer: Any, when: datetime) -> None:
    freezer.move_to(when)
    async_fire_time_changed(hass, when)
    await hass.async_block_till_done()


SOFIA = {"id": "sofia", "name": "Sofia", "color": "#FF8800", "role": "child"}


def _echo(hass: HomeAssistant, name: str) -> None:
    """An Echo speaker of the Alexa Media platform, as the entity registry has it."""
    er.async_get(hass).async_get_or_create(
        "media_player", "alexa_media", name, suggested_object_id=name
    )


async def test_alexa_announce_is_used_instead_of_tts(hass: HomeAssistant, freezer: Any) -> None:
    freezer.move_to(local(10))
    _echo(hass, "cucina")
    await _setup(
        hass,
        [
            {
                **SOFIA,
                CONF_SPEAKER: "media_player.cucina",
                CONF_ALEXA_NOTIFY: "media_player.cucina",
            }
        ],
        reminders={"channels": ["speaker"], "tts_entity": "tts.test"},
    )
    alexa = async_mock_service(hass, "notify", "alexa_media")
    speak = async_mock_service(hass, "tts", "speak")
    await _add(hass)

    await _tick(hass, freezer, local(14, 30))
    assert len(alexa) == 1
    assert alexa[0].data["target"] == ["media_player.cucina"]
    assert alexa[0].data["data"] == {"type": "announce"}
    assert "Dentista" in alexa[0].data["message"]
    assert speak == []


async def test_tts_is_used_when_no_alexa_service(hass: HomeAssistant, freezer: Any) -> None:
    freezer.move_to(local(10))
    await _setup(
        hass,
        [{**SOFIA, CONF_SPEAKER: "media_player.cucina"}],
        reminders={"channels": ["speaker"], "tts_entity": "tts.test"},
    )
    speak = async_mock_service(hass, "tts", "speak")
    await _add(hass)

    await _tick(hass, freezer, local(14, 30))
    assert len(speak) == 1


async def test_popup_uses_browser_mod_and_keeps_the_tablet_notification(
    hass: HomeAssistant, freezer: Any
) -> None:
    freezer.move_to(local(10))
    await _setup(
        hass,
        [{**SOFIA, CONF_PHONE_NOTIFY: "mobile_app_sofia"}],
        reminders={"channels": ["tablet", "popup"]},
    )
    popup = async_mock_service(hass, "browser_mod", "popup")
    tablet = async_mock_service(hass, "persistent_notification", "create")
    await _add(hass)

    await _tick(hass, freezer, local(14, 30))
    assert len(popup) == 1
    assert popup[0].data["title"] == "Promemoria"
    assert "Dentista" in popup[0].data["content"]
    assert popup[0].data["dismissable"] is True
    assert len(tablet) == 1


async def test_popup_is_skipped_quietly_without_browser_mod(
    hass: HomeAssistant, freezer: Any
) -> None:
    freezer.move_to(local(10))
    await _setup(
        hass,
        [{**SOFIA, CONF_PHONE_NOTIFY: "mobile_app_sofia"}],
        reminders={"channels": ["popup"]},
    )
    assert not hass.services.has_service("browser_mod", "popup")
    await _add(hass)

    # No browser_mod service: nothing is sent and nothing raises.
    await _tick(hass, freezer, local(14, 30))
