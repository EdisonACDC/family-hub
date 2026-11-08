"""Calendar entities: one native calendar per Family Hub category.

Events of every person that belong to a category are shown in that category's
calendar. Each event may list several persons.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.components.calendar.const import CalendarEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, OPT_CATEGORIES, OPT_PERSONS, OPT_SHARED_USERS
from .models import FamilyHubConfigEntry
from .storage import EventStore


def _offsets_text(offsets: Any) -> str:
    """The reminder minutes as text: "default" when the family's own are used."""
    if offsets is None:
        return "default"
    return ",".join(str(int(o)) for o in offsets)


@dataclass
class FamilyHubEvent(CalendarEvent):
    """A calendar event plus the family fields the tablet add-on needs.

    ``person_ids`` is the comma-separated person ids of the event. Calendar service
    responses turn lists into text, so a plain string is used. ``record_id`` is the
    stored id (the calendar API does not always return ``uid``).
    """

    person_ids: str = ""
    record_id: str = ""
    shift_id: str = ""
    # Minutes before the start, comma separated; "" for none; "default" for the family's own.
    reminder_offsets: str = "default"


SUPPORTED_FEATURES = (
    CalendarEntityFeature.CREATE_EVENT
    | CalendarEntityFeature.UPDATE_EVENT
    | CalendarEntityFeature.DELETE_EVENT
)


def is_all_day(value: date | datetime) -> bool:
    """Return True for a plain date (all-day event)."""
    return not isinstance(value, datetime)


def localize(value: date | datetime) -> date | datetime:
    """Attach the local time zone to naive datetimes."""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=dt_util.get_default_time_zone())
    return value


def as_datetime(value: date | datetime) -> datetime:
    """Convert a date or datetime to an aware datetime for comparisons."""
    if isinstance(value, datetime):
        return localize(value)  # type: ignore[return-value]
    return datetime.combine(value, datetime.min.time(), dt_util.get_default_time_zone())


def deserialize_time(raw: str, all_day: bool) -> date | datetime:
    """Read a stored ISO string back into a date or datetime."""
    if all_day:
        return date.fromisoformat(raw)
    return datetime.fromisoformat(raw)


def _given(event: dict[str, Any], *keys: str) -> Any:
    """First key present in ``event``. HA sends dtstart/dtend; start/end also work."""
    for key in keys:
        if key in event:
            return event[key]
    return None


def validate_range(start: date | datetime, end: date | datetime) -> None:
    """Raise if start/end mix types or end is not after start."""
    if is_all_day(start) != is_all_day(end):
        raise ServiceValidationError("start and end must both be dates or both be date-times")
    if as_datetime(end) <= as_datetime(start):
        raise ServiceValidationError("end must be after start")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FamilyHubConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one calendar entity per configured category."""
    data = entry.runtime_data
    calendars = [
        FamilyHubCalendar(
            data.store,
            entry.entry_id,
            category,
            entry.options.get(OPT_PERSONS, []),
            entry.options.get(OPT_SHARED_USERS, []),
        )
        for category in entry.options.get(OPT_CATEGORIES, [])
    ]
    data.calendars = {cal.category_id: cal for cal in calendars}
    # External calendars (ICS from a link or a file) are read-only entities of their own.
    external = data.external.build_entities() if data.external else []
    async_add_entities([*calendars, *external])


class FamilyHubCalendar(CalendarEntity):
    """A calendar that stores its events in the Family Hub store."""

    # The name the family chose is the friendly name; the entity id is set below.
    _attr_has_entity_name = False
    _attr_supported_features = SUPPORTED_FEATURES

    def __init__(
        self,
        store: EventStore,
        entry_id: str,
        category: dict[str, str],
        persons: list[dict[str, Any]] | None = None,
        shared_users: list[str] | None = None,
    ) -> None:
        self._store = store
        self._shared_users = list(shared_users or [])
        self.category_id = category["id"]
        self._attr_name = category["name"]
        self._attr_unique_id = f"{entry_id}_{self.category_id}"
        # The device keeps the calendars together; its name is not added to the friendly name
        # (has_entity_name is off), so the name shown is the one the family chose.
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry_id)}, name="Family Hub")
        self._stem = "".join(ch if ch.isalnum() else "_" for ch in category["name"].lower()).strip(
            "_"
        )
        self._persons = [dict(person) for person in persons or []]

    # ----- helpers -------------------------------------------------------

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The category id, so the tablet add-on can pass it to family_hub.add_event."""
        return {
            "category_id": self.category_id,
            "persons": [
                {
                    "id": person["id"],
                    "name": person.get("name", ""),
                    "role": person.get("role", "adult"),
                    "ha_user_id": person.get("ha_user_id"),
                }
                for person in self._persons
            ],
            "shared_users": list(self._shared_users),
        }

    def _records(self) -> list[dict[str, Any]]:
        return [r for r in self._store.events.values() if r["category"] == self.category_id]

    def _to_calendar_event(self, record: dict[str, Any]) -> CalendarEvent:
        all_day = bool(record["all_day"])
        return FamilyHubEvent(
            person_ids=",".join(record.get("persons", [])),
            record_id=record["uid"],
            shift_id=record.get("shift_id", ""),
            reminder_offsets=_offsets_text(record.get("reminder_offsets")),
            uid=record["uid"],
            summary=record["summary"],
            start=deserialize_time(record["start"], all_day),
            end=deserialize_time(record["end"], all_day),
            description=record.get("description") or None,
            location=record.get("location") or None,
        )

    async def _async_save_and_refresh(self) -> None:
        await self._store.async_save()
        self.async_write_ha_state()

    def _get_own_record(self, uid: str) -> dict[str, Any]:
        record = self._store.events.get(uid)
        if record is None or record["category"] != self.category_id:
            raise ServiceValidationError(f"Event {uid} not found in {self.name}")
        return record

    # ----- CalendarEntity API -------------------------------------------

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next event that has not ended yet."""
        now = dt_util.now()
        upcoming = [
            ev
            for ev in (self._to_calendar_event(r) for r in self._records())
            if as_datetime(ev.end) > now
        ]
        return min(upcoming, key=lambda ev: as_datetime(ev.start), default=None)

    @property
    def suggested_object_id(self) -> str:
        """calendar.family_hub_<name>, as before, while the name shown is the category's."""
        return self._stem

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return events overlapping the requested window."""
        events = [self._to_calendar_event(r) for r in self._records()]
        in_window = [
            ev
            for ev in events
            if as_datetime(ev.start) < end_date and as_datetime(ev.end) > start_date
        ]
        return sorted(in_window, key=lambda ev: as_datetime(ev.start))

    async def async_create_event(self, **kwargs: Any) -> None:
        """Entry point used by the calendar platform (create_event)."""
        await self.async_add_event(
            summary=kwargs["summary"],
            start=_given(kwargs, "dtstart", "start"),
            end=_given(kwargs, "dtend", "end"),
            description=kwargs.get("description"),
            location=kwargs.get("location"),
            persons=kwargs.get("persons"),
        )

    async def async_update_event(
        self,
        uid: str,
        event: dict[str, Any],
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Update an event; keys missing from ``event`` keep their value."""
        if recurrence_id is not None:
            raise ServiceValidationError("Recurring events are not supported yet")
        record = self._get_own_record(uid)
        old_start = deserialize_time(record["start"], record["all_day"])
        old_end = deserialize_time(record["end"], record["all_day"])

        new_start = _given(event, "dtstart", "start")
        new_end = _given(event, "dtend", "end")
        start = localize(old_start if new_start is None else new_start)
        end = localize(old_end if new_end is None else new_end)
        validate_range(start, end)

        record["summary"] = event.get("summary", record["summary"])
        record["description"] = event.get("description", record.get("description", ""))
        record["location"] = event.get("location", record.get("location", ""))
        record["persons"] = list(event.get("persons", record.get("persons", [])))
        if record["start"] != start.isoformat() or record["end"] != end.isoformat():
            # A moved event gets reminders again, even after "Fatto" / stop_reminder.
            record["reminders_off"] = False
        record["start"] = start.isoformat()
        record["end"] = end.isoformat()
        record["all_day"] = is_all_day(start)
        if "reminder_offsets" in event:
            record["reminder_offsets"] = event["reminder_offsets"]
        if "all_day_reminder" in event:
            record["all_day_reminder"] = event["all_day_reminder"]
        await self._async_save_and_refresh()

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Delete an event."""
        if recurrence_id is not None:
            raise ServiceValidationError("Recurring events are not supported yet")
        self._get_own_record(uid)
        del self._store.events[uid]
        await self._async_save_and_refresh()

    # ----- Family Hub API (used by the actions) -------------------------

    async def async_add_event(
        self,
        *,
        summary: str,
        start: date | datetime,
        end: date | datetime,
        description: str | None = None,
        location: str | None = None,
        persons: list[str] | None = None,
        reminder_offsets: list[int] | None = None,
        all_day_reminder: str | None = None,
        shift_id: str | None = None,
    ) -> str:
        """Store a new event and return its uid."""
        start = localize(start)
        end = localize(end)
        validate_range(start, end)
        uid = uuid.uuid4().hex
        self._store.events[uid] = {
            "uid": uid,
            "category": self.category_id,
            "summary": summary,
            "description": description or "",
            "location": location or "",
            "persons": list(persons or []),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "all_day": is_all_day(start),
            "reminder_offsets": None if reminder_offsets is None else list(reminder_offsets),
            "all_day_reminder": all_day_reminder or None,
            "shift_id": shift_id or "",
        }
        await self._async_save_and_refresh()
        return uid
