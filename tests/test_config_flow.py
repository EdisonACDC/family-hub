"""Tests for the config flow and options flow."""

from __future__ import annotations

import probatio as vol
import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
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

USER_INPUT = {
    CONF_FAMILY_NAME: "Esempio",
    CONF_LANGUAGE: "it",
    CONF_FIRST_WEEKDAY: "monday",
}


async def test_user_flow_creates_entry_with_default_categories(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Esempio"
    assert result["options"][CONF_LANGUAGE] == "it"

    entry = result["result"]
    assert entry.options[OPT_PERSONS] == []
    assert [c["id"] for c in entry.options[OPT_CATEGORIES]] == [c["id"] for c in DEFAULT_CATEGORIES]
    await hass.async_block_till_done()
    assert hass.states.get("calendar.family_hub_famiglia") is not None
    # The tablet shows the family's own name for the category, whatever Home Assistant calls it.
    state = hass.states.get("calendar.family_hub_famiglia")
    assert state is not None and state.attributes["category_name"] == "Famiglia"


async def test_user_flow_rejects_blank_name(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_FAMILY_NAME: "   "}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_FAMILY_NAME: "empty_name"}


async def test_only_one_instance_allowed(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, data=USER_INPUT, options={}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_add_person_and_category(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=USER_INPUT,
        options={OPT_PERSONS: [], OPT_CATEGORIES: [dict(c) for c in DEFAULT_CATEGORIES]},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_person"}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"name": "Sofia", "color": "#FF8800", "role": "child"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert len(entry.options[OPT_PERSONS]) == 1
    assert entry.options[OPT_PERSONS][0]["name"] == "Sofia"

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_category"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "Sport", "color": "#00AAFF"}
    )
    await hass.async_block_till_done()
    assert "Sport" in [c["name"] for c in entry.options[OPT_CATEGORIES]]
    assert hass.states.get("calendar.family_hub_sport") is not None


async def test_options_rejects_invalid_colour(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data=USER_INPUT, options={OPT_PERSONS: [], OPT_CATEGORIES: []}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_person"}
    )
    # The schema rejects the colour before the step runs.
    with pytest.raises(vol.Invalid):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {"name": "X", "color": "blue", "role": "adult"}
        )
    assert entry.options[OPT_PERSONS] == []
