"""Calendar entities: one native calendar per Family Hub category.

Events of every person that belong to a category are shown in that category's
calendar. Each event may list several persons.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.components.calendar.const import CalendarEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from . import recurrence
from .const import DOMAIN, OPT_CATEGORIES, OPT_PERSONS, OPT_SHARED_USERS
from .models import FamilyHubConfigEntry
from .storage import EventStore


def _offsets_text(offsets: Any) -> str:
    """The reminder minutes as text: "default" when the family's own are used."""
    if offsets is None:
        return "default"
    return ",".join(str(int(o)) for o in offsets)


def notify_text(notify: dict[str, Any] | None) -> str:
    """An event's own channels as text for the tablet: "phone,alexa|all|80", or ""."""
    if not notify:
        return ""
    volume = notify.get("alexa_volume")
    return "|".join(
        [
            ",".join(notify.get("channels", [])),
            str(notify.get("alexa_target") or ""),
            "" if volume is None else str(int(volume)),
            str(notify.get("phone_sound") or ""),
        ]
    )


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
    # The event's own notification channels, as text: "phone,alexa|media_player.x|80";
    # "" when the persons' own settings apply.
    notify: str = ""


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
    # Repeating events are written out a year ahead, and a little further every day.
    if extend_series(data.store, dt_util.now()):
        await data.store.async_save()

    async def _extend_daily(_now: datetime) -> None:
        if extend_series(data.store, dt_util.now()):
            await data.store.async_save()
            for cal in data.calendars.values():
                cal.async_write_ha_state()

    entry.async_on_unload(async_track_time_change(hass, _extend_daily, hour=3, minute=20, second=0))
    # External calendars (ICS from a link or a file) are read-only entities of their own.
    external = data.external.build_entities() if data.external else []
    _remove_orphans(hass, entry, {str(c.unique_id) for c in [*calendars, *external]})
    _reserve_entity_ids(hass, entry, calendars)
    async_add_entities([*calendars, *external])


def _remove_orphans(hass: HomeAssistant, entry: FamilyHubConfigEntry, keep: set[str]) -> None:
    """Remove from the entity registry the calendars this entry made earlier whose category or
    ICS file has been removed. Their entity ids are not reused for a new one of the same name."""
    registry = er.async_get(hass)
    for item in er.async_entries_for_config_entry(registry, entry.entry_id):
        if item.domain == "calendar" and item.unique_id not in keep:
            registry.async_remove(item.entity_id)


def _reserve_entity_ids(
    hass: HomeAssistant, entry: FamilyHubConfigEntry, calendars: list[FamilyHubCalendar]
) -> None:
    """Enter each new calendar in the registry as calendar.family_hub_<category id> before it is
    added. Home Assistant adds the device's area and name to a new entity's id, so without this the
    id depends on where the device sits. An entry that already exists keeps its id, even if the
    family renamed it by hand. A taken id gets a number from Home Assistant."""
    registry = er.async_get(hass)
    for cal in calendars:
        registry.async_get_or_create(
            "calendar",
            DOMAIN,
            str(cal.unique_id),
            config_entry=entry,
            suggested_object_id=f"family_hub_{cal.stem}",
        )


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
        # The category id, cleaned, for the entity id calendar.family_hub_<stem> (see
        # _reserve_entity_ids).
        self.stem = "".join(ch if ch.isalnum() else "_" for ch in self.category_id.lower()).strip(
            "_"
        )
        self._persons = [dict(person) for person in persons or []]

    # ----- helpers -------------------------------------------------------

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The category id, so the tablet add-on can pass it to family_hub.add_event."""
        return {
            "category_id": self.category_id,
            # The family's name for it. The friendly name is Home Assistant's and may add the
            # device's name, so the tablet shows this one.
            "category_name": str(self._attr_name or ""),
            "persons": [
                {
                    "id": person["id"],
                    "name": person.get("name", ""),
                    "role": person.get("role", "adult"),
                    "ha_user_id": person.get("ha_user_id"),
                    "color": person.get("color") or "",
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
            notify=notify_text(record.get("notify")),
            uid=record["uid"],
            summary=record["summary"],
            start=deserialize_time(record["start"], all_day),
            end=deserialize_time(record["end"], all_day),
            description=record.get("description") or None,
            location=record.get("location") or None,
            rrule=record.get("rrule") or None,
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
            rrule=kwargs.get("rrule"),
        )

    async def async_update_event(
        self,
        uid: str,
        event: dict[str, Any],
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Update an event; keys missing from ``event`` keep their value.

        For a repeating event, ``recurrence_range`` THISANDFUTURE changes this occurrence and the
        ones after it (they become a series of their own from here); ALL changes every occurrence;
        no range changes this occurrence only. A new ``rrule`` writes the occurrences again from the
        occurrence that was edited.
        """
        record = self._get_own_record(uid)
        affected = self._affected(record, recurrence_range)
        all_day = bool(record["all_day"])
        new_start = _given(event, "dtstart", "start")
        new_end = _given(event, "dtend", "end")
        start = localize(_when(record) if new_start is None else new_start)
        end = localize(_when_end(record) if new_end is None else new_end)
        validate_range(start, end)

        rule = recurrence.validate(event["rrule"]) if event.get("rrule") else None
        if "rrule" in event and rule != (record.get("rrule") or None):
            self._rewrite_series(record, affected, event, start, end, rule, recurrence_range)
            await self._async_save_and_refresh()
            return

        delta = as_datetime(start) - as_datetime(_when(record))
        for item in affected:
            _apply_fields(item, event)
            moved_start = as_datetime(_when(item)) + delta
            moved_end = as_datetime(_when_end(item)) + delta
            if item is record:
                moved_start = as_datetime(start)
                moved_end = as_datetime(end)
            if moved_start != as_datetime(_when(item)) or moved_end != as_datetime(_when_end(item)):
                # A moved event gets reminders again, even after "Fatto" / stop_reminder.
                item["reminders_off"] = False
            item["start"] = _stored(moved_start, all_day or is_all_day(start))
            item["end"] = _stored(moved_end, all_day or is_all_day(start))
            item["all_day"] = is_all_day(start) if item is record else bool(item["all_day"])
        if recurrence_range == "THISANDFUTURE" and record.get("series"):
            self._divide(record, affected)
        await self._async_save_and_refresh()

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Delete an event. For a repeating event, the range says which occurrences: this one only
        (no range), this one and the ones after it (THISANDFUTURE), or all of them (ALL)."""
        record = self._get_own_record(uid)
        for item in self._affected(record, recurrence_range):
            self._store.events.pop(item["uid"], None)
        await self._async_save_and_refresh()

    # ----- repeating events --------------------------------------------

    def _series_records(self, series: str) -> list[dict[str, Any]]:
        return sorted(
            (r for r in self._store.events.values() if r.get("series") == series),
            key=lambda r: as_datetime(_when(r)),
        )

    def _affected(
        self, record: dict[str, Any], recurrence_range: str | None
    ) -> list[dict[str, Any]]:
        """The occurrences a change or a delete reaches, as the range says."""
        series = record.get("series")
        if not series or recurrence_range not in ("THISANDFUTURE", "ALL"):
            return [record]
        items = self._series_records(series)
        if recurrence_range == "ALL":
            return items
        return [r for r in items if as_datetime(_when(r)) >= as_datetime(_when(record))]

    def _divide(self, record: dict[str, Any], affected: list[dict[str, Any]]) -> None:
        """A change from one occurrence on divides the series: the later ones get their own series
        and, if the series has a count, the count that is left."""
        series = str(record["series"])
        items = self._series_records(series)
        if len(affected) >= len(items):
            return
        before = len(items) - len(affected)
        new_series = uuid.uuid4().hex
        rule = str(record.get("rrule") or "")
        for item in affected:
            item["series"] = new_series
            if rule:
                item["rrule"] = recurrence.remaining(rule, before)

    def _rewrite_series(
        self,
        record: dict[str, Any],
        affected: list[dict[str, Any]],
        event: dict[str, Any],
        start: date | datetime,
        end: date | datetime,
        rule: str | None,
        recurrence_range: str | None,
    ) -> None:
        """A new repeat rule: the affected occurrences are replaced by occurrences of the new rule,
        from the edited one on. Values not given keep the edited occurrence's own."""
        values = _values(record)
        _apply_fields(values, event)
        for item in affected:
            self._store.events.pop(item["uid"], None)
        self._insert_series(values, rule, start, end)

    def _insert_series(
        self,
        values: dict[str, Any],
        rule: str | None,
        start: date | datetime,
        end: date | datetime,
    ) -> str:
        """Store one event, or every occurrence of a rule, and return the first uid."""
        series = uuid.uuid4().hex if rule else ""
        starts = self._occurrence_starts(rule, start) if rule else [start]
        span = as_datetime(end) - as_datetime(start)
        all_day = is_all_day(start)
        first_uid = ""
        for when in starts:
            uid = uuid.uuid4().hex
            when_end = as_datetime(when) + span
            self._store.events[uid] = {
                **values,
                "uid": uid,
                "category": self.category_id,
                "start": _stored(when, all_day),
                "end": _stored(when_end, all_day),
                "all_day": all_day,
                "series": series,
                "rrule": rule or "",
            }
            first_uid = first_uid or uid
        return first_uid

    def _occurrence_starts(self, rule: str, start: date | datetime) -> list[Any]:
        """The start of each occurrence, written out to the horizon."""
        now = dt_util.now()
        if is_all_day(start):
            horizon = recurrence.horizon_for(now, as_datetime(start)).date()
            return recurrence.all_day_starts(rule, start, horizon)
        horizon = recurrence.horizon_for(now, as_datetime(start))
        return recurrence.starts_for(rule, as_datetime(start), horizon)

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
        notify: dict[str, Any] | None = None,
        rrule: str | None = None,
    ) -> str:
        """Store a new event (or every occurrence of a repeat rule) and return the first uid."""
        start = localize(start)
        end = localize(end)
        validate_range(start, end)
        rule = recurrence.validate(rrule) if rrule else None
        values = {
            "summary": summary,
            "description": description or "",
            "location": location or "",
            "persons": list(persons or []),
            "reminder_offsets": None if reminder_offsets is None else list(reminder_offsets),
            "all_day_reminder": all_day_reminder or None,
            "shift_id": shift_id or "",
            "notify": notify,
        }
        uid = self._insert_series(values, rule, start, end)
        await self._async_save_and_refresh()
        return uid


# The values an occurrence keeps from its event (the rest belongs to the occurrence itself).
_FIELDS = (
    "summary",
    "description",
    "location",
    "persons",
    "reminder_offsets",
    "all_day_reminder",
    "shift_id",
    "notify",
)


def _values(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in _FIELDS}


def _apply_fields(item: dict[str, Any], event: dict[str, Any]) -> None:
    """Copy the fields the change gives; the others keep their value."""
    item["summary"] = event.get("summary", item.get("summary", ""))
    item["description"] = event.get("description", item.get("description", ""))
    item["location"] = event.get("location", item.get("location", ""))
    item["persons"] = list(event.get("persons", item.get("persons", [])))
    if "reminder_offsets" in event:
        item["reminder_offsets"] = event["reminder_offsets"]
    if "all_day_reminder" in event:
        item["all_day_reminder"] = event["all_day_reminder"]
    if "notify" in event:
        item["notify"] = event["notify"]


def _when(record: dict[str, Any]) -> date | datetime:
    return deserialize_time(record["start"], bool(record["all_day"]))


def _when_end(record: dict[str, Any]) -> date | datetime:
    return deserialize_time(record["end"], bool(record["all_day"]))


def _stored(value: Any, all_day: bool) -> str:
    """The text a record keeps for a start or an end: a date, or a date and time."""
    if all_day:
        return (value.date() if isinstance(value, datetime) else value).isoformat()
    return str(value.isoformat())


def extend_series(store: EventStore, now: datetime) -> bool:
    """Write the occurrences of repeating events on, up to the horizon. True if any were added."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in store.events.values():
        if record.get("series") and record.get("rrule"):
            groups.setdefault(str(record["series"]), []).append(record)
    target = now + timedelta(days=recurrence.HORIZON_DAYS)
    added = False
    for items in groups.values():
        items.sort(key=lambda r: as_datetime(_when(r)))
        first, last = items[0], items[-1]
        last_when = as_datetime(_when(last))
        if last_when >= target - timedelta(days=60):
            continue
        rule = str(last["rrule"])
        all_day = bool(last["all_day"])
        starts: list[Any]
        if all_day:
            starts = recurrence.all_day_starts(rule, _when(first), target.date())
        else:
            starts = recurrence.starts_for(rule, as_datetime(_when(first)), target)
        span = as_datetime(_when_end(last)) - as_datetime(_when(last))
        for when in starts:
            if as_datetime(when) <= last_when:
                continue
            uid = uuid.uuid4().hex
            store.events[uid] = {
                **last,
                "uid": uid,
                "start": _stored(when, all_day),
                "end": _stored(as_datetime(when) + span, all_day),
                "reminders_off": False,
                "sent": [],
            }
            added = True
    return added
