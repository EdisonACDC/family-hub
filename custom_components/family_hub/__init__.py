"""The Family Hub integration: family calendars, reminders and actions."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.typing import ConfigType

from .api import async_register_commands
from .const import (
    ACTION_EVENT,
    ACTION_PREFIX,
    CONF_FAMILY_NAME,
    CONF_FIRST_WEEKDAY,
    CONF_LANGUAGE,
)
from .external import ExternalManager, action_from, is_waste_uid
from .models import FamilyHubConfigEntry, FamilyHubData
from .reminders import ReminderManager
from .services import async_register_services
from .storage import EventStore

PLATFORMS: list[Platform] = [Platform.CALENDAR]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register actions and websocket commands. Runs once, even without a config entry."""
    async_register_services(hass)
    async_register_commands(hass)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Version 1 kept the family name, language and first weekday in data; move them to options."""
    if entry.version == 1:
        data = dict(entry.data)
        options = dict(entry.options)
        for key in (CONF_FAMILY_NAME, CONF_LANGUAGE, CONF_FIRST_WEEKDAY):
            if key in data:
                options[key] = data.pop(key)
        hass.config_entries.async_update_entry(entry, data=data, options=options, version=2)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: FamilyHubConfigEntry) -> bool:
    """Set up a Family Hub config entry."""
    store = EventStore(hass, entry.entry_id)
    await store.async_load()
    reminders = ReminderManager(hass, entry, store)
    external = ExternalManager(hass, entry)
    entry.runtime_data = FamilyHubData(store=store, reminders=reminders, external=external)
    entry.async_on_unload(reminders.async_stop)
    await reminders.async_start()
    await external.async_load()
    entry.async_on_unload(external.async_stop)
    await external.async_start()

    @callback
    def _on_notification_action(event: Event) -> None:
        action = event.data.get("action")
        if isinstance(action, str) and action.startswith(ACTION_PREFIX):
            parts = action.split("_")
            if len(parts) >= 3 and is_waste_uid(parts[-1] if parts[1] != "SNOOZE" else parts[3]):
                command, uid, minutes = action_from(parts)
                hass.async_create_task(external.async_action(command, uid, minutes))
                return
            hass.async_create_task(reminders.async_handle_action(action))

    entry.async_on_unload(hass.bus.async_listen(ACTION_EVENT, _on_notification_action))

    # Changing persons or categories in the options flow reloads the entry.
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FamilyHubConfigEntry) -> bool:
    """Unload a Family Hub config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
