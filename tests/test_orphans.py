"""A calendar whose category is removed leaves the entity registry: no empty calendar stays behind
under its old entity id (which a new category of the same name would otherwise collide with)."""

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


def _categories(*names: str) -> list[dict[str, str]]:
    return [{"id": name.lower(), "name": name, "color": "#3B82F6"} for name in names]


async def test_a_removed_category_takes_its_calendar_out_of_the_registry(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
        options={
            OPT_PERSONS: [],
            OPT_CATEGORIES: _categories("Famiglia", "Scuola"),
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)

    def calendars() -> set[str]:
        return {
            item.entity_id
            for item in er.async_entries_for_config_entry(registry, entry.entry_id)
            if item.domain == "calendar"
        }

    assert len(calendars()) == 2
    school = next(item for item in calendars() if item.endswith("scuola"))

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, OPT_CATEGORIES: _categories("Famiglia")}
    )
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert len(calendars()) == 1
    assert registry.async_get(school) is None
