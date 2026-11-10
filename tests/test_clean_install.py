"""A clean install, end to end (rule C): the integration is added, the guide's first step makes the
family, the calendars are there at once, and an event can be created and read back.

The variants are the installs that must work: an area on the device, English, German, no Alexa
and no mobile app, and a user who is not an administrator opening the page.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from homeassistant import config_entries
from homeassistant.components.websocket_api import ERR_UNAUTHORIZED
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.plugins import WebSocketGenerator

from custom_components.family_hub.const import (
    CONF_FAMILY_NAME,
    CONF_FIRST_WEEKDAY,
    CONF_LANGUAGE,
    DOMAIN,
    OPT_CATEGORIES,
    default_categories,
)


async def _install(hass: HomeAssistant, language: str) -> Any:
    """The guide's first step, as the user fills it in. Returns the new config entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_FAMILY_NAME: "Casa Esempio", CONF_LANGUAGE: language, CONF_FIRST_WEEKDAY: "monday"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    await hass.async_block_till_done()
    return result["result"]


def _calendars(hass: HomeAssistant, entry: Any) -> list[er.RegistryEntry]:
    registry = er.async_get(hass)
    return [
        item
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        if item.domain == "calendar"
    ]


def _no_alexa_no_app(hass: HomeAssistant) -> None:
    """The variant with no Alexa Media Player and no Companion app: nothing to send to."""
    assert not hass.services.has_service("notify", "alexa_media")
    assert not hass.config_entries.async_entries("mobile_app")


@pytest.mark.parametrize(
    ("language", "with_area"),
    [("en", False), ("de", False), ("it", True), ("en", True)],
    ids=["english", "german", "area-on-device", "english-area"],
)
async def test_clean_install_shows_calendars_and_takes_an_event(
    hass: HomeAssistant, language: str, with_area: bool
) -> None:
    _no_alexa_no_app(hass)
    entry = await _install(hass, language)

    calendars = _calendars(hass, entry)
    assert calendars, "the calendars must exist right after the install"
    for item in calendars:
        # Visible at once: a state exists without any reload or restart.
        assert hass.states.get(item.entity_id) is not None, item.entity_id
        assert item.entity_id.startswith("calendar.family_hub_"), item.entity_id

    if with_area:
        # Home Assistant may put the device in an area; the calendars must still be found.
        area = ar.async_get(hass).async_create("Soggiorno")
        devices = dr.async_get(hass)
        (device,) = dr.async_entries_for_config_entry(devices, entry.entry_id)
        devices.async_update_device(device.id, area_id=area.id)

    # The family's own names, in the language chosen at install.
    names = {c["id"]: c["name"] for c in default_categories(language)}
    famiglia = hass.states.get("calendar.family_hub_famiglia")
    assert famiglia is not None
    assert famiglia.attributes["category_name"] == names["famiglia"]
    assert [c["id"] for c in entry.options[OPT_CATEGORIES]] == list(names)

    # An event can be created in the first calendar, and it reads back.
    entity_id = "calendar.family_hub_famiglia"
    start = dt_util.now().replace(microsecond=0) + timedelta(hours=1)
    end = start + timedelta(hours=1)
    await hass.services.async_call(
        "calendar",
        "create_event",
        {"summary": "Visita", "start_date_time": start, "end_date_time": end},
        target={"entity_id": entity_id},
        blocking=True,
    )
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "start_date_time": start - timedelta(minutes=1),
            "end_date_time": end + timedelta(minutes=1),
        },
        target={"entity_id": entity_id},
        blocking=True,
        return_response=True,
    )
    assert [e["summary"] for e in response[entity_id]["events"]] == ["Visita"]


async def test_the_version_and_setup_are_known_to_any_signed_in_user(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
) -> None:
    """A user who is not an administrator can ask the integration's version and whether it is
    set up (the page needs it to say what is missing); family settings stay for administrators."""
    await _install(hass, "en")
    integration = await async_get_integration(hass, DOMAIN)

    reader = await hass_ws_client(hass, hass_read_only_access_token)
    await reader.send_json({"id": 1, "type": "family_hub/info"})
    reply = await reader.receive_json()
    assert reply["success"] is True
    assert reply["result"] == {"version": str(integration.version), "configured": True}

    await reader.send_json({"id": 2, "type": "family_hub/config/get"})
    refused = await reader.receive_json()
    assert refused["success"] is False
    assert refused["error"]["code"] == ERR_UNAUTHORIZED


async def test_the_version_is_reported_before_any_family_is_made(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Right after the integration is added, before the guide: configured is False, so the page
    says to finish the setup instead of showing an empty calendar list. (Home Assistant loads the
    integration, and its commands, without any entry: async_setup_component does that here.)"""
    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "family_hub/info"})
    reply = await client.receive_json()
    assert reply["success"] is True
    assert reply["result"]["configured"] is False
    assert reply["result"]["version"]
