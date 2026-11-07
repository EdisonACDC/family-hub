"""Migration to config entry version 2, and the websocket commands used by the setup guide."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.family_hub.const import (
    CONF_FAMILY_NAME,
    CONF_FIRST_WEEKDAY,
    CONF_LANGUAGE,
    DEFAULT_CATEGORIES,
    DOMAIN,
    OPT_CATEGORIES,
    OPT_PERSONS,
)


@pytest.fixture(autouse=True)
def _notify_services(hass: HomeAssistant) -> None:
    """The phone and Echo services the sample people use exist in Home Assistant."""
    er.async_get(hass).async_get_or_create(
        "media_player", "alexa_media", "kueche", suggested_object_id="kueche"
    )
    for name in ("mobile_app_sofia",):
        hass.services.async_register("notify", name, lambda call: None)


async def _entry(hass: HomeAssistant, version: int = 2) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=version,
        title="Esempio",
        data={}
        if version == 2
        else {CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
        options={
            **(
                {CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"}
                if version == 2
                else {}
            ),
            OPT_PERSONS: [],
            OPT_CATEGORIES: [dict(c) for c in DEFAULT_CATEGORIES],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _config(**overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "sources": {"todo": [], "calendars": []},
        "family": {
            CONF_FAMILY_NAME: "Famiglia Esempio",
            CONF_LANGUAGE: "de",
            CONF_FIRST_WEEKDAY: "sunday",
            "time_format": "24h",
            "country": "Deutschland",
            "region": "Bayern",
        },
        "screen": {"theme": "dark"},
        "persons": [
            {
                "name": "Sofia",
                "color": "#FF8800",
                "role": "child",
                "phone_notify": "mobile_app_sofia",
                "alexa_notify": "media_player.kueche",
                "ha_user_id": "u-sofia",
                "quiet_start": "21:30",
                "quiet_end": "07:00",
            },
            {"name": "Mamma", "color": "#2563EB", "role": "adult", "ha_user_id": "u-mamma"},
        ],
        "categories": [
            {"name": "Familie", "color": "#3B82F6"},
            {"name": "Sport", "color": "#10B981"},
        ],
        "reminders": {
            "offsets": [30, 10],
            "channels": ["phone", "tablet"],
            "quiet_start": "22:00",
            "quiet_end": "07:00",
            "snooze_minutes": 10,
            "tts_entity": "",
            "morning_summary": "07:00",
            "evening_summary": "",
            "all_day_reminder": "19:00",
        },
    }
    config.update(overrides)
    return config


async def test_version_one_entry_moves_family_settings_to_options(hass: HomeAssistant) -> None:
    entry = await _entry(hass, version=1)
    assert entry.version == 2
    assert entry.data == {}
    assert entry.options[CONF_FAMILY_NAME] == "Esempio"
    assert entry.options[CONF_LANGUAGE] == "it"
    assert entry.options[CONF_FIRST_WEEKDAY] == "monday"


async def test_get_returns_the_whole_configuration(
    hass: HomeAssistant, hass_ws_client: Any
) -> None:
    await _entry(hass)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "family_hub/config/get"})
    reply = await client.receive_json()
    assert reply["success"] is True
    result = reply["result"]
    assert result["family"][CONF_FAMILY_NAME] == "Esempio"
    assert result["family"]["time_format"] == "24h"
    assert result["screen"] == {"theme": "auto"}
    assert [c["id"] for c in result["categories"]] == [c["id"] for c in DEFAULT_CATEGORIES]
    assert result["reminders"]["offsets"] == [30, 10]


async def test_save_stores_the_configuration_and_reloads(
    hass: HomeAssistant, hass_ws_client: Any
) -> None:
    entry = await _entry(hass)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 2, "type": "family_hub/config/save", "config": _config()})
    reply = await client.receive_json()
    assert reply["success"] is True, reply
    await hass.async_block_till_done()

    assert entry.options[CONF_FAMILY_NAME] == "Famiglia Esempio"
    assert entry.options[CONF_LANGUAGE] == "de"
    assert entry.options["theme"] == "dark"
    sofia, mamma = entry.options[OPT_PERSONS]
    assert sofia["name"] == "Sofia" and sofia["ha_user_id"] == "u-sofia"
    assert sofia["quiet_start"] == "21:30" and "tts" not in sofia
    assert mamma["id"] and "phone_notify" not in mamma
    assert [c["id"] for c in entry.options[OPT_CATEGORIES]] == ["familie", "sport"]
    assert entry.options["reminders"]["evening_summary"] is None
    assert hass.states.get("calendar.family_hub_sport") is not None


async def test_round_trip_keeps_the_configuration(hass: HomeAssistant, hass_ws_client: Any) -> None:
    await _entry(hass)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 3, "type": "family_hub/config/save", "config": _config()})
    assert (await client.receive_json())["success"] is True
    await hass.async_block_till_done()
    await client.send_json({"id": 4, "type": "family_hub/config/get"})
    first = (await client.receive_json())["result"]
    await client.send_json({"id": 5, "type": "family_hub/config/save", "config": first})
    assert (await client.receive_json())["success"] is True
    await hass.async_block_till_done()
    await client.send_json({"id": 6, "type": "family_hub/config/get"})
    second = (await client.receive_json())["result"]
    assert second == first


async def test_invalid_configuration_is_refused_and_nothing_changes(
    hass: HomeAssistant, hass_ws_client: Any
) -> None:
    entry = await _entry(hass)
    before = dict(entry.options)
    client = await hass_ws_client(hass)
    bad_cases = [
        _config(persons=[{"name": "X", "color": "red", "role": "adult"}]),
        _config(persons=[{"name": "X", "color": "#FFFFFF", "role": "boss"}]),
        _config(reminders={**_config()["reminders"], "quiet_start": "25:00"}),
        _config(reminders={**_config()["reminders"], "offsets": [-5]}),
        _config(reminders={**_config()["reminders"], "channels": ["fax"]}),
        _config(categories=[]),
        _config(categories=[{"name": "A", "color": "#FFFFFF"}, {"name": "A", "color": "#FFFFFF"}]),
    ]
    for n, config in enumerate(bad_cases, start=10):
        await client.send_json({"id": n, "type": "family_hub/config/save", "config": config})
        reply = await client.receive_json()
        assert reply["success"] is False, config
        assert reply["error"]["code"] == "invalid_config"
    assert dict(entry.options) == before


async def test_non_admin_cannot_read_or_save(
    hass: HomeAssistant, hass_ws_client: Any, hass_read_only_access_token: str
) -> None:
    entry = await _entry(hass)
    before = dict(entry.options)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json({"id": 1, "type": "family_hub/config/get"})
    assert (await client.receive_json())["success"] is False
    await client.send_json({"id": 2, "type": "family_hub/config/save", "config": _config()})
    assert (await client.receive_json())["success"] is False
    assert dict(entry.options) == before


async def test_configured_flag_is_set_by_the_guide_only(
    hass: HomeAssistant, hass_ws_client: Any
) -> None:
    await _entry(hass)
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "family_hub/config/get"})
    assert (await client.receive_json())["result"]["configured"] is False
    await client.send_json({"id": 2, "type": "family_hub/config/save", "config": _config()})
    assert (await client.receive_json())["success"] is True
    await hass.async_block_till_done()
    await client.send_json({"id": 3, "type": "family_hub/config/get"})
    assert (await client.receive_json())["result"]["configured"] is True


async def test_category_with_events_cannot_be_removed(
    hass: HomeAssistant, hass_ws_client: Any
) -> None:
    entry = await _entry(hass)
    await hass.services.async_call(
        DOMAIN,
        "add_event",
        {"category": "famiglia", "summary": "Pranzo", "start": "2027-01-10 12:00:00"},
        blocking=True,
    )
    client = await hass_ws_client(hass)
    keep_scuola = {
        "family": _config()["family"],
        "screen": {"theme": "auto"},
        "persons": [],
        "categories": [{"id": "scuola", "name": "Scuola", "color": "#10B981"}],
        "reminders": _config()["reminders"],
    }
    before = dict(entry.options)
    await client.send_json({"id": 1, "type": "family_hub/config/save", "config": keep_scuola})
    reply = await client.receive_json()
    assert reply["success"] is False
    assert reply["error"]["code"] == "category_in_use"
    assert "Famiglia" in reply["error"]["message"]
    assert dict(entry.options) == before


async def test_wrong_types_are_invalid_config(hass: HomeAssistant, hass_ws_client: Any) -> None:
    entry = await _entry(hass)
    before = dict(entry.options)
    client = await hass_ws_client(hass)
    bad = [
        _config(persons="Sofia"),
        _config(categories={"name": "Scuola"}),
        _config(categories=["Scuola"]),
        _config(family=[]),
        _config(screen="dark"),
        _config(reminders=None),
        _config(persons=[None]),
    ]
    for n, config in enumerate(bad, start=10):
        await client.send_json({"id": n, "type": "family_hub/config/save", "config": config})
        reply = await client.receive_json()
        assert reply["success"] is False, config
        assert reply["error"]["code"] == "invalid_config", reply
    assert dict(entry.options) == before


async def test_external_sources_are_checked_and_stored(
    hass: HomeAssistant, hass_ws_client: Any
) -> None:
    entry = await _entry(hass)
    hass.states.async_set("todo.spesa", "0", {"friendly_name": "Spesa"})
    hass.states.async_set("calendar.rifiuti", "off", {"friendly_name": "Rifiuti"})
    client = await hass_ws_client(hass)

    message_id = 0

    async def save(sources: Any) -> dict[str, Any]:
        nonlocal message_id
        message_id += 1
        await client.send_json(
            {
                "id": message_id,
                "type": "family_hub/config/save",
                "config": _config(sources=sources),
            }
        )
        return await client.receive_json()

    ok = await save({"todo": ["todo.spesa"], "calendars": ["calendar.rifiuti"], "weather": []})
    assert ok["success"] is True, ok
    assert entry.options["sources"] == {
        "todo": ["todo.spesa"],
        "calendars": ["calendar.rifiuti"],
        "weather": [],
    }

    bad = [
        {"todo": ["todo.inesistente"]},
        {"todo": ["calendar.rifiuti"]},
        {"calendars": ["todo.spesa"]},
        {"calendars": ["calendar.family_hub_famiglia"]},
        {"todo": "todo.spesa"},
        {"calendars": ["calendar.*"]},
    ]
    for sources in bad:
        reply = await save(sources)
        assert reply["success"] is False, sources
        assert reply["error"]["code"] == "invalid_config"
    assert entry.options["sources"] == {
        "todo": ["todo.spesa"],
        "calendars": ["calendar.rifiuti"],
        "weather": [],
    }
