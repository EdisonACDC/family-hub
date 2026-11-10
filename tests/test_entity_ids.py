"""Entity ids get the Family Hub prefix, so they never clash with existing calendars."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
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

CATEGORIES = [
    {"id": "famiglia", "name": "Famiglia", "color": "#3B82F6"},
    {"id": "scuola e lavoro", "name": "Scuola: lavoro", "color": "#10B981"},
]


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


async def test_calendar_ids_do_not_depend_on_the_device_area(hass: HomeAssistant) -> None:
    """The device sits in an area before the calendars are made (rule A): the ids are still
    calendar.family_hub_<category id>, not calendar.<area>_family_hub_<category id>."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
        options={OPT_PERSONS: [], OPT_CATEGORIES: CATEGORIES},
    )
    entry.add_to_hass(hass)
    area = ar.async_get(hass).async_create("Ingresso casa")
    devices = dr.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="Family Hub",
    )
    devices.async_update_device(device.id, area_id=area.id)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    ids = {
        item.unique_id: item.entity_id
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        if item.domain == "calendar"
    }
    assert ids == {
        f"{entry.entry_id}_famiglia": "calendar.family_hub_famiglia",
        f"{entry.entry_id}_scuola e lavoro": "calendar.family_hub_scuola_e_lavoro",
    }
    assert hass.states.get("calendar.family_hub_famiglia") is not None
    assert hass.states.get("calendar.family_hub_scuola_e_lavoro") is not None
