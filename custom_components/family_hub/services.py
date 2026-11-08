"""Actions (services) of Family Hub.

One action per operation, never one per person. Persons are passed as data.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, cast

import probatio as vol  # Home Assistant's schema library (voluptuous successor).
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .calendar import FamilyHubCalendar, deserialize_time, localize
from .const import (
    ATTR_ALEXA_TARGET,
    ATTR_ALEXA_VOLUME,
    ATTR_ALL_DAY_REMINDER,
    ATTR_CATEGORY,
    ATTR_CHANNELS,
    ATTR_DESCRIPTION,
    ATTR_END,
    ATTR_ENTRY_ID,
    ATTR_LOCATION,
    ATTR_MINUTES,
    ATTR_PERSONS,
    ATTR_PHONE_SOUND,
    ATTR_REMINDER_OFFSETS,
    ATTR_SHIFT_ID,
    ATTR_START,
    ATTR_SUMMARY,
    ATTR_UID,
    DOMAIN,
    EVENT_CHANNELS,
    OPT_PERSONS,
    PHONE_SOUNDS,
    SERVICE_ADD_EVENT,
    SERVICE_DELETE_EVENT,
    SERVICE_MOVE_EVENT,
    SERVICE_SNOOZE_REMINDER,
    SERVICE_STOP_REMINDER,
    SERVICE_UPDATE_EVENT,
)
from .external import SNOOZE_MINUTES, is_waste_uid
from .models import FamilyHubConfigEntry


def _parse_time(value: Any) -> date | datetime:
    """Parse a date ("2026-11-10") or a date-time ("2026-11-10 15:00").

    Date-only strings are checked first: cv.datetime also accepts them and returns midnight,
    which would silently turn an all-day event into a timed one.
    """
    if isinstance(value, (date, datetime)):
        return value
    text = cv.string(value).strip()
    try:
        if len(text) == 10:
            return date.fromisoformat(text)
        return cv.datetime(text)
    except (ValueError, vol.Invalid) as err:
        raise vol.Invalid(f"invalid date or date-time: {text}") from err


TIME = _parse_time
SUMMARY = vol.All(cv.string, vol.Length(min=1, max=255))
HH_MM = vol.Match(r"^([01]\d|2[0-3]):[0-5]\d$")
PERSONS = vol.All(cv.ensure_list, [cv.string])
# Minutes before the start, e.g. [30, 10]. Empty list = no reminders for this event.
REMINDER_OFFSETS = vol.All(cv.ensure_list, [cv.positive_int])

# The event's own notification channels (see ATTR_CHANNELS). None in update_event goes back
# to the persons' own settings.
CHANNELS = vol.Any(None, vol.All(cv.ensure_list, [vol.In(EVENT_CHANNELS)]))
ALEXA_TARGET = vol.Any(None, cv.string)
ALEXA_VOLUME = vol.Any(None, vol.All(vol.Coerce(int), vol.Range(min=0, max=100)))
NOTIFY_FIELDS = {
    vol.Optional(ATTR_CHANNELS): CHANNELS,
    vol.Optional(ATTR_ALEXA_TARGET): ALEXA_TARGET,
    vol.Optional(ATTR_ALEXA_VOLUME): ALEXA_VOLUME,
    vol.Optional(ATTR_PHONE_SOUND): vol.Any(None, vol.In(PHONE_SOUNDS)),
}


def _notify_of(data: dict[str, Any]) -> dict[str, Any] | None:
    """The event's own channels from the action data, or None (the persons' settings)."""
    channels = data.get(ATTR_CHANNELS)
    if channels is None:
        return None
    target = data.get(ATTR_ALEXA_TARGET) or None
    if target is not None and target != "all" and not str(target).startswith("media_player."):
        raise ServiceValidationError("alexa_target must be 'all' or a media_player entity")
    return {
        "channels": [c for c in EVENT_CHANNELS if c in channels],
        "alexa_target": target,
        "alexa_volume": data.get(ATTR_ALEXA_VOLUME),
        "phone_sound": data.get(ATTR_PHONE_SOUND) or None,
    }


ADD_EVENT_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Required(ATTR_CATEGORY): cv.string,
        vol.Required(ATTR_SUMMARY): SUMMARY,
        vol.Required(ATTR_START): TIME,
        vol.Optional(ATTR_END): TIME,
        vol.Optional(ATTR_DESCRIPTION): cv.string,
        vol.Optional(ATTR_LOCATION): cv.string,
        vol.Optional(ATTR_PERSONS, default=list): PERSONS,
        vol.Optional(ATTR_REMINDER_OFFSETS): REMINDER_OFFSETS,
        vol.Optional(ATTR_ALL_DAY_REMINDER): HH_MM,
        vol.Optional(ATTR_SHIFT_ID): cv.string,
        **NOTIFY_FIELDS,
    }
)

UPDATE_EVENT_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Required(ATTR_UID): cv.string,
        vol.Optional(ATTR_SUMMARY): SUMMARY,
        vol.Optional(ATTR_START): TIME,
        vol.Optional(ATTR_END): TIME,
        vol.Optional(ATTR_DESCRIPTION): cv.string,
        vol.Optional(ATTR_LOCATION): cv.string,
        vol.Optional(ATTR_PERSONS): PERSONS,
        vol.Optional(ATTR_REMINDER_OFFSETS): REMINDER_OFFSETS,
        vol.Optional(ATTR_ALL_DAY_REMINDER): HH_MM,
        **NOTIFY_FIELDS,
    }
)

SNOOZE_REMINDER_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Required(ATTR_UID): cv.string,
        vol.Optional(ATTR_MINUTES): vol.All(cv.positive_int, vol.Range(min=1, max=1440)),
    }
)

STOP_REMINDER_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Required(ATTR_UID): cv.string,
    }
)

DELETE_EVENT_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Required(ATTR_UID): cv.string,
    }
)

MOVE_EVENT_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Required(ATTR_UID): cv.string,
        vol.Required(ATTR_START): TIME,
        # If omitted, the event keeps its duration.
        vol.Optional(ATTR_END): TIME,
    }
)


def _resolve_entry(hass: HomeAssistant, entry_id: str | None) -> FamilyHubConfigEntry:
    loaded = [
        cast(FamilyHubConfigEntry, entry)
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    if entry_id is not None:
        for entry in loaded:
            if entry.entry_id == entry_id:
                return entry
        raise ServiceValidationError(f"No loaded Family Hub entry with id {entry_id}")
    if not loaded:
        raise ServiceValidationError("Family Hub is not set up")
    if len(loaded) > 1:
        raise ServiceValidationError("More than one Family Hub entry exists; pass entry_id")
    return loaded[0]


def _calendar_for(entry: FamilyHubConfigEntry, category_id: str) -> FamilyHubCalendar:
    calendar = entry.runtime_data.calendars.get(category_id)
    if calendar is None:
        raise ServiceValidationError(f"Unknown category '{category_id}'")
    return calendar


def _check_persons(entry: FamilyHubConfigEntry, persons: list[str]) -> list[str]:
    known = {person["id"] for person in entry.options.get(OPT_PERSONS, [])}
    unknown = [person for person in persons if person not in known]
    if unknown:
        raise ServiceValidationError(f"Unknown person(s): {', '.join(unknown)}")
    return persons


def _find_event(entry: FamilyHubConfigEntry, uid: str) -> tuple[FamilyHubCalendar, dict[str, Any]]:
    record = entry.runtime_data.store.events.get(uid)
    if record is None:
        raise ServiceValidationError(f"Unknown event '{uid}'")
    return _calendar_for(entry, record["category"]), record


def _normalize(value: date | datetime) -> date | datetime:
    return localize(value)


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register the Family Hub actions once per Home Assistant instance."""
    if hass.services.has_service(DOMAIN, SERVICE_ADD_EVENT):
        return

    async def add_event(call: ServiceCall) -> None:
        entry = _resolve_entry(hass, call.data.get(ATTR_ENTRY_ID))
        calendar = _calendar_for(entry, call.data[ATTR_CATEGORY])
        start = _normalize(call.data[ATTR_START])
        end = _normalize(call.data.get(ATTR_END) or _default_end(start))
        await calendar.async_add_event(
            summary=call.data[ATTR_SUMMARY],
            start=start,
            end=end,
            description=call.data.get(ATTR_DESCRIPTION),
            location=call.data.get(ATTR_LOCATION),
            persons=_check_persons(entry, call.data[ATTR_PERSONS]),
            reminder_offsets=call.data.get(ATTR_REMINDER_OFFSETS),
            all_day_reminder=call.data.get(ATTR_ALL_DAY_REMINDER),
            shift_id=call.data.get(ATTR_SHIFT_ID),
            notify=_notify_of(dict(call.data)),
        )

    async def update_event(call: ServiceCall) -> None:
        entry = _resolve_entry(hass, call.data.get(ATTR_ENTRY_ID))
        calendar, _ = _find_event(entry, call.data[ATTR_UID])
        changes: dict[str, Any] = {}
        for key in (ATTR_SUMMARY, ATTR_DESCRIPTION, ATTR_LOCATION):
            if key in call.data:
                changes[key] = call.data[key]
        if ATTR_PERSONS in call.data:
            changes[ATTR_PERSONS] = _check_persons(entry, call.data[ATTR_PERSONS])
        for key in (ATTR_START, ATTR_END):
            if key in call.data:
                changes[key] = _normalize(call.data[key])
        if ATTR_REMINDER_OFFSETS in call.data:
            changes[ATTR_REMINDER_OFFSETS] = call.data[ATTR_REMINDER_OFFSETS]
        if ATTR_ALL_DAY_REMINDER in call.data:
            changes[ATTR_ALL_DAY_REMINDER] = call.data[ATTR_ALL_DAY_REMINDER]
        if ATTR_CHANNELS in call.data:
            changes["notify"] = _notify_of(dict(call.data))
        await calendar.async_update_event(call.data[ATTR_UID], changes)

    async def delete_event(call: ServiceCall) -> None:
        entry = _resolve_entry(hass, call.data.get(ATTR_ENTRY_ID))
        calendar, _ = _find_event(entry, call.data[ATTR_UID])
        await calendar.async_delete_event(call.data[ATTR_UID])

    async def snooze_reminder(call: ServiceCall) -> None:
        entry = _resolve_entry(hass, call.data.get(ATTR_ENTRY_ID))
        if is_waste_uid(str(call.data[ATTR_UID])) and entry.runtime_data.external:
            minutes = int(call.data.get(ATTR_MINUTES) or SNOOZE_MINUTES)
            await entry.runtime_data.external.async_action("snooze", call.data[ATTR_UID], minutes)
            return
        _find_event(entry, call.data[ATTR_UID])
        reminders = entry.runtime_data.reminders
        minutes = call.data.get(ATTR_MINUTES) or reminders.settings["snooze_minutes"]
        await reminders.async_snooze(call.data[ATTR_UID], int(minutes))

    async def stop_reminder(call: ServiceCall) -> None:
        entry = _resolve_entry(hass, call.data.get(ATTR_ENTRY_ID))
        if is_waste_uid(str(call.data[ATTR_UID])) and entry.runtime_data.external:
            await entry.runtime_data.external.async_action("done", call.data[ATTR_UID])
            return
        _find_event(entry, call.data[ATTR_UID])
        await entry.runtime_data.reminders.async_stop_event(call.data[ATTR_UID])

    async def move_event(call: ServiceCall) -> None:
        entry = _resolve_entry(hass, call.data.get(ATTR_ENTRY_ID))
        calendar, record = _find_event(entry, call.data[ATTR_UID])
        start = _normalize(call.data[ATTR_START])
        if ATTR_END in call.data:
            end = _normalize(call.data[ATTR_END])
        else:
            old_start = deserialize_time(record["start"], record["all_day"])
            old_end = deserialize_time(record["end"], record["all_day"])
            end = start + (old_end - old_start)
        await calendar.async_update_event(call.data[ATTR_UID], {"start": start, "end": end})

    hass.services.async_register(DOMAIN, SERVICE_ADD_EVENT, add_event, schema=ADD_EVENT_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_UPDATE_EVENT, update_event, schema=UPDATE_EVENT_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE_EVENT, delete_event, schema=DELETE_EVENT_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_MOVE_EVENT, move_event, schema=MOVE_EVENT_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_SNOOZE_REMINDER, snooze_reminder, schema=SNOOZE_REMINDER_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_STOP_REMINDER, stop_reminder, schema=STOP_REMINDER_SCHEMA
    )


def _default_end(start: date | datetime) -> date | datetime:
    if isinstance(start, datetime):
        return start + timedelta(hours=1)
    return start + timedelta(days=1)
