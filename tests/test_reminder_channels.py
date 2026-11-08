"""Tests for the Alexa announce channel and the optional browser_mod popup channel."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
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


async def test_an_event_uses_its_own_channels_echo_and_volume(
    hass: HomeAssistant, freezer: Any
) -> None:
    """ "Avvisa su" on the event: only Alexa, on the kitchen Echo at 80 %, instead of Sofia's
    phone; the event's choice is kept and shown to the tablet as text."""
    freezer.move_to(local(10))
    _echo(hass, "cucina")
    _echo(hass, "salotto")
    entry = await _setup(
        hass,
        [
            {
                **SOFIA,
                CONF_PHONE_NOTIFY: "mobile_app_sofia",
                CONF_ALEXA_NOTIFY: "media_player.salotto",
                "channels": ["phone", "tablet"],
            }
        ],
        reminders={"channels": ["phone", "tablet"]},
    )
    phone = async_mock_service(hass, "notify", "mobile_app_sofia")
    alexa = async_mock_service(hass, "notify", "alexa_media")
    async_mock_service(hass, "media_player", "volume_set")
    tablet = async_mock_service(hass, "persistent_notification", "create")
    await hass.services.async_call(
        DOMAIN,
        "add_event",
        {
            "category": "famiglia",
            "summary": "Dentista",
            "start": "2026-11-10 15:00:00",
            "persons": ["sofia"],
            "channels": ["alexa"],
            "alexa_target": "media_player.cucina",
            "alexa_volume": 80,
        },
        blocking=True,
    )
    (record,) = entry.runtime_data.store.events.values()
    assert record["notify"] == {
        "channels": ["alexa"],
        "alexa_target": "media_player.cucina",
        "alexa_volume": 80,
        "phone_sound": None,
    }
    state = hass.states.get("calendar.family_hub_famiglia")
    assert state is not None

    await _tick(hass, freezer, local(14, 30))
    assert phone == []
    assert tablet == []
    assert len(alexa) == 1
    assert alexa[0].data["target"] == ["media_player.cucina"]

    # Back to the persons' own settings: the phone again.
    await hass.services.async_call(
        DOMAIN, "update_event", {"uid": record["uid"], "channels": None}, blocking=True
    )
    assert record["notify"] is None
    await _tick(hass, freezer, local(14, 50))
    assert len(phone) == 1


async def test_quiet_hours_still_apply_to_the_event_channels(
    hass: HomeAssistant, freezer: Any
) -> None:
    freezer.move_to(local(10))
    _echo(hass, "cucina")
    await _setup(
        hass,
        [{**SOFIA, "quiet_start": "14:00", "quiet_end": "16:00"}],
        reminders={"channels": ["phone", "tablet"]},
    )
    alexa = async_mock_service(hass, "notify", "alexa_media")
    await hass.services.async_call(
        DOMAIN,
        "add_event",
        {
            "category": "famiglia",
            "summary": "Dentista",
            "start": "2026-11-10 15:00:00",
            "persons": ["sofia"],
            "channels": ["alexa"],
            "alexa_target": "all",
        },
        blocking=True,
    )
    await _tick(hass, freezer, local(14, 30))
    assert alexa == []


async def test_a_wrong_echo_is_refused(hass: HomeAssistant) -> None:
    import pytest
    from homeassistant.exceptions import ServiceValidationError

    await _setup(hass, [SOFIA])
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "add_event",
            {
                "category": "famiglia",
                "summary": "X",
                "start": "2026-11-10 15:00:00",
                "channels": ["alexa"],
                "alexa_target": "light.cucina",
            },
            blocking=True,
        )


def _phone_app(hass: HomeAssistant, name: str, os_name: str) -> None:
    """A phone with the Home Assistant Companion app, as mobile_app registers it."""
    MockConfigEntry(
        domain="mobile_app", title=name, data={"device_name": name, "os_name": os_name}
    ).add_to_hass(hass)


@pytest.mark.parametrize(
    ("sound", "os_name", "expected"),
    [
        (
            "important",
            "iOS",
            {"push": {"sound": "default", "interruption-level": "time-sensitive"}},
        ),
        (
            "critical",
            "iOS",
            {"push": {"sound": {"name": "default", "critical": 1, "volume": 1.0}}},
        ),
        (
            "important",
            "Android",
            {
                "priority": "high",
                "ttl": 0,
                "importance": "high",
                "channel": "Promemoria Family Hub",
            },
        ),
        (
            "critical",
            "Android",
            {
                "priority": "high",
                "ttl": 0,
                "importance": "high",
                "channel": "Promemoria Family Hub urgenti",
                "media_stream": "alarm_stream",
            },
        ),
        ("normal", "iOS", {}),
    ],
)
async def test_the_reminder_sound_on_ios_and_android(
    hass: HomeAssistant, freezer: Any, sound: str, os_name: str, expected: dict[str, Any]
) -> None:
    freezer.move_to(local(10))
    _phone_app(hass, "Telefono Sofia", os_name)
    await _setup(
        hass,
        [{**SOFIA, CONF_PHONE_NOTIFY: "mobile_app_telefono_sofia", "phone_sound": sound}],
        reminders={"channels": ["phone"]},
    )
    phone = async_mock_service(hass, "notify", "mobile_app_telefono_sofia")
    await _add(hass)
    await _tick(hass, freezer, local(14, 30))
    assert len(phone) == 1
    data = dict(phone[0].data["data"])
    for key in ("tag", "actions"):
        data.pop(key, None)
    assert data == expected


async def test_an_unknown_phone_gets_both_and_the_event_can_change_the_sound(
    hass: HomeAssistant, freezer: Any
) -> None:
    from custom_components.family_hub.notifier import sound_data

    both = sound_data("important", None)
    assert both["push"]["interruption-level"] == "time-sensitive"
    assert both["priority"] == "high"
    freezer.move_to(local(10))
    await _setup(
        hass,
        [{**SOFIA, CONF_PHONE_NOTIFY: "mobile_app_sofia", "phone_sound": "critical"}],
        reminders={"channels": ["phone"]},
    )
    phone = async_mock_service(hass, "notify", "mobile_app_sofia")
    await hass.services.async_call(
        DOMAIN,
        "add_event",
        {
            "category": "famiglia",
            "summary": "Dentista",
            "start": "2026-11-10 15:00:00",
            "persons": ["sofia"],
            "channels": ["phone"],
            "phone_sound": "normal",
        },
        blocking=True,
    )
    await _tick(hass, freezer, local(14, 30))
    assert len(phone) == 1
    assert "push" not in phone[0].data["data"] and "priority" not in phone[0].data["data"]
