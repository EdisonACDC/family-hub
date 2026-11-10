"""The first form offers the languages by their own names, not as bare codes."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.family_hub.const import CONF_LANGUAGE, DOMAIN


async def test_language_field_shows_names(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    schema = result["data_schema"].schema
    (field,) = [key for key in schema if key == CONF_LANGUAGE]
    options = schema[field].config["options"]
    assert options == [
        {"value": "it", "label": "Italiano"},
        {"value": "de", "label": "Deutsch"},
        {"value": "en", "label": "English"},
    ]
