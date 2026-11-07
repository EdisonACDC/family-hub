"""Entity ids get the Family Hub prefix, so they never clash with existing calendars."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.family_hub.const import (
    CONF_FAMILY_NAME,
    CONF_FIRST_WEEKDAY,
    CONF_LANGUAGE,
    DOMAIN,
    OPT_CATEGORIES,
    OPT_PERSONS,
)


async def test_existing_calendar_famiglia_is_left_alone(hass: HomeAssistant) -> None:
    registry = er.async_get(hass)
    # A calendar.famiglia that another integration already owns.
    registry.async_get_or_create(
        "calendar", "other_integration", "pre-existing", suggested_object_id="famiglia"
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
        options={
            OPT_PERSONS: [],
            OPT_CATEGORIES: [{"id": "famiglia", "name": "Famiglia", "color": "#3B82F6"}],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    ours = registry.async_get("calendar.family_hub_famiglia")
    assert ours is not None
    assert ours.platform == DOMAIN
    existing = registry.async_get("calendar.famiglia")
    assert existing is not None
    assert existing.unique_id == "pre-existing"
