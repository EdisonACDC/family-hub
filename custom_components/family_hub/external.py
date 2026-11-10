"""External calendars: an ICS file, from a link or uploaded, shown read only.

- The content lives in Home Assistant's storage (one store per config entry). A link is
  downloaded again every 12 hours and by the "Aggiorna ora" button. If a download fails, the
  last valid copy stays and the error and the last update time are kept.
- Parsing uses the ``ical`` library that Home Assistant's own calendars use. Recurring events
  (RRULE) and all-day events are expanded.
- Limits: http, https or webcal only; 20 s timeout; 5 MB; 5000 events; the file must be
  valid ICS. The link can hold a token, so it is never written to a log.
- Rubbish (rifiuti): one reminder per moment for all pickups of the day, the evening before
  and the morning of it, with "Fatto" (which also ends the morning one of the same pickup)
  and "Posticipa 1 ora". Holidays only when the calendar asks for a notice the day before
  the return.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import aiohttp
from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from ical.calendar import Calendar
from ical.calendar_stream import IcsCalendarStream

from . import manual_waste
from .const import CONF_LANGUAGE, DOMAIN, OPT_MANUAL_WASTE, OPT_PERSONS, OPT_REMINDERS
from .notifier import Delivery, async_dismiss, async_send
from .waste import default_waste_types, labels_for, type_of, types_from_options

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

LOGGER = logging.getLogger(__name__)

TYPES = ["rifiuti", "vacanze_scuola", "vacanze_asilo", "festivita", "altro"]
VACATION_TYPES = {"vacanze_scuola", "vacanze_asilo", "festivita"}
# The words of a summary line, by the family's language: "Rifiuti: Organico", a holiday's name.
SUMMARY_TEXTS: dict[str, dict[str, str]] = {
    "it": {
        "rubbish": "Rifiuti",
        "vacanze_scuola": "Vacanze scuola",
        "vacanze_asilo": "Vacanze asilo",
        "festivita": "Festività",
    },
    "de": {
        "rubbish": "Müll",
        "vacanze_scuola": "Schulferien",
        "vacanze_asilo": "Kita-Ferien",
        "festivita": "Feiertag",
    },
    "en": {
        "rubbish": "Waste",
        "vacanze_scuola": "School holidays",
        "vacanze_asilo": "Nursery holidays",
        "festivita": "Public holiday",
    },
}
MAX_BYTES = 5 * 1024 * 1024
MAX_EVENTS = 5000
TIMEOUT_SECONDS = 20
REFRESH_EVERY = timedelta(hours=12)
STORAGE_VERSION = 1
OPT_EXTERNAL = "external_calendars"
OPT_WASTE_STYLE = "waste_styles"
# Reminder ids of rubbish start with this and contain no "_" (the phone's buttons split on it).
WASTE_UID_PREFIX = "ext-"
SNOOZE_MINUTES = 60


def waste_kind(title: str, language: str = "en") -> str | None:
    """The id of the default rubbish type of a language a title belongs to ("altro" when none
    matches)."""
    kind = type_of(title, default_waste_types(language))
    return kind["id"] if kind else None


TEXTS: dict[str, dict[str, str]] = {
    "it": {"today": "Oggi", "tomorrow": "Domani", "return": "Domani si rientra", "title": "Ritiro"},
    "de": {
        "today": "Heute",
        "tomorrow": "Morgen",
        "return": "Morgen ist Rückkehr",
        "title": "Abholung",
    },
    "en": {"today": "Today", "tomorrow": "Tomorrow", "return": "Back tomorrow", "title": "Pickup"},
}
FATTO = {"it": "Fatto", "de": "Erledigt", "en": "Done"}
POSTICIPA = {"it": "Posticipa 1 ora", "de": "1 Stunde später", "en": "Snooze 1 hour"}


class ExternalError(ValueError):
    """A problem with an external calendar. ``code`` is what the add-on translates."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def check_url(url: str) -> str:
    """Return the http(s) address to download. webcal:// is fetched as https://."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https", "webcal") or not parts.netloc:
        raise ExternalError("bad_url")
    scheme = "https" if parts.scheme == "webcal" else parts.scheme
    return f"{scheme}://{parts.netloc}{parts.path}" + (f"?{parts.query}" if parts.query else "")


def parse(text: str) -> Calendar:
    """Parse ICS text. Raises ExternalError for invalid or too large calendars."""
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ExternalError("too_large")
    if "BEGIN:VCALENDAR" not in text:
        raise ExternalError("invalid_ics")
    try:
        calendar = IcsCalendarStream.calendar_from_ics(text)
    except Exception as err:  # the library raises several error types for bad input
        raise ExternalError("invalid_ics") from err
    if len(calendar.events) > MAX_EVENTS:
        raise ExternalError("too_many_events")
    return calendar


async def download(hass: HomeAssistant, url: str) -> str:
    """Download an ICS file with the limits above. The URL is never logged."""
    address = check_url(url)
    session = async_get_clientsession(hass)
    chunks: list[bytes] = []
    try:
        async with session.get(
            address, timeout=aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
        ) as resp:
            if resp.status >= 400:
                raise ExternalError("download_failed")
            size = 0
            async for chunk in resp.content.iter_chunked(64 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ExternalError("too_large")
                chunks.append(chunk)
    except ExternalError:
        raise
    except (aiohttp.ClientError, TimeoutError) as err:
        LOGGER.warning("Calendar download failed (%s)", type(err).__name__)
        raise ExternalError("download_failed") from err
    try:
        return b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError as err:
        raise ExternalError("invalid_ics") from err


def _on_day(calendar: Calendar, day: date) -> list[Any]:
    """The events (recurrences expanded) that overlap one day, in the local time zone."""
    zone = dt_util.get_default_time_zone()
    start = datetime.combine(day, datetime.min.time(), zone)
    return list(calendar.timeline_tz(zone).overlapping(start, start + timedelta(days=1)))


def _to_event(event: Any) -> CalendarEvent:
    return CalendarEvent(
        summary=str(event.summary or ""),
        start=event.start,
        end=event.end,
        description=getattr(event, "description", None),
        location=getattr(event, "location", None),
    )


class ExternalCalendar(CalendarEntity):
    """A read-only calendar from an ICS file.

    Its entity id is calendar.family_hub_ext_<id>; its name (friendly name) is the name the
    family chose.
    """

    _attr_has_entity_name = False

    def __init__(self, entry_id: str, source: dict[str, Any], text: str | None) -> None:
        self.source_id = str(source["id"])
        self._attr_name = str(source.get("name") or f"ext_{self.source_id}")
        self._attr_unique_id = f"{entry_id}_ext_{self.source_id}"
        self._calendar: Calendar | None = self._parsed(text)

    @property
    def suggested_object_id(self) -> str:
        """The entity id stays calendar.family_hub_ext_<id>, whatever the name is."""
        return f"family_hub_ext_{self.source_id}"

    @staticmethod
    def _parsed(text: str | None) -> Calendar | None:
        if not text:
            return None
        try:
            return parse(text)
        except ExternalError:
            return None

    @property
    def event(self) -> CalendarEvent | None:
        """The next or current event (what the calendar card shows first)."""
        if self._calendar is None:
            return None
        timeline = self._calendar.timeline_tz(dt_util.get_default_time_zone())
        return next((_to_event(e) for e in timeline.active_after(dt_util.now())), None)

    @property
    def calendar(self) -> Calendar | None:
        """The parsed calendar, or None when there is no valid copy."""
        return self._calendar

    @callback
    def set_content(self, text: str | None) -> None:
        """Replace the calendar with a new ICS text and tell Home Assistant."""
        self._calendar = self._parsed(text)
        if self.hass is not None:
            self.async_write_ha_state()

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Events that overlap the window (recurrences expanded)."""
        if self._calendar is None:
            return []
        timeline = self._calendar.timeline_tz(dt_util.get_default_time_zone())
        return [_to_event(e) for e in timeline.overlapping(start_date, end_date)]


class ExternalManager:
    """Owns the stored contents, the calendar entities, the 12-hour refresh and the reminders."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.external.{entry.entry_id}"
        )
        self.data: dict[str, Any] = {"contents": {}, "status": {}, "done": []}
        self.entities: dict[str, ExternalCalendar] = {}
        self._unsubs: list[Any] = []
        self._snoozed: dict[str, Any] = {}
        self._pending: dict[str, tuple[dict[str, Any], str, str, str]] = {}

    # ---- storage ----

    async def async_load(self) -> None:
        loaded = await self._store.async_load()
        if loaded:
            self.data = {
                "contents": dict(loaded.get("contents", {})),
                "status": dict(loaded.get("status", {})),
                "done": list(loaded.get("done", [])),
            }

    async def async_save(self) -> None:
        await self._store.async_save(self.data)

    def sources(self) -> list[dict[str, Any]]:
        found = [dict(s) for s in self._entry.options.get(OPT_EXTERNAL, [])]
        schedule = self.manual_schedule()
        if schedule["rules"] or schedule["extra"] or schedule["moves"]:
            # The pickups the family made by hand: a source like a file, with no link to refresh.
            found.append(
                {
                    "id": manual_waste.SOURCE_ID,
                    "name": manual_waste.calendar_name(self.language()),
                    "type": "rifiuti",
                    "manual": True,
                }
            )
        return found

    def manual_schedule(self) -> dict[str, Any]:
        """The pickups made by hand, as stored (empty when there are none)."""
        stored = self._entry.options.get(OPT_MANUAL_WASTE)
        return dict(stored) if isinstance(stored, dict) else manual_waste.empty()

    def waste_types(self) -> list[dict[str, str]]:
        """The rubbish types (label, icon, text to look for, colour): the family's or defaults."""
        return types_from_options(dict(self._entry.options))

    def language(self) -> str:
        """The family's language, for the words of a summary (English if none is set)."""
        return str(self._entry.options.get(CONF_LANGUAGE) or "en")

    def waste_styles(self) -> dict[str, str]:
        """The colour of each rubbish type, by id."""
        return {kind["id"]: kind["color"] for kind in self.waste_types()}

    def status(self, source_id: str) -> dict[str, Any]:
        return dict(self.data["status"].get(source_id, {}))

    def content(self, source_id: str) -> str | None:
        if source_id == manual_waste.SOURCE_ID:
            labels = {kind["id"]: kind["label"] for kind in self.waste_types()}
            return manual_waste.ics_text(self.manual_schedule(), labels, today=dt_util.now().date())
        value = self.data["contents"].get(source_id)
        return value if isinstance(value, str) else None

    # ---- lifecycle ----

    def build_entities(self) -> list[ExternalCalendar]:
        """One entity per source, with its last valid content."""
        self.entities = {
            s["id"]: ExternalCalendar(self._entry.entry_id, s, self.content(s["id"]))
            for s in self.sources()
        }
        return list(self.entities.values())

    async def async_start(self) -> None:
        self._unsubs.append(async_track_time_interval(self._hass, self._refresh_all, REFRESH_EVERY))
        for source in self.sources():
            if source.get("type") == "rifiuti" or source.get("return_notice"):
                self._schedule_reminders(source)
        # Home Assistant calendars chosen as rubbish in the guide's Fonti step.
        for source in self.home_assistant_rubbish():
            self._schedule_reminders(source)

    def home_assistant_rubbish(self) -> list[dict[str, Any]]:
        """A reminder source for each Home Assistant calendar whose type is rubbish. Its id has
        no "_" or "." (the reminder buttons are parsed by "_")."""
        styles = self._entry.options.get("sources", {}).get("calendar_styles", {})
        found = []
        for entity_id, style in styles.items():
            if style.get("type") != "rifiuti":
                continue
            slug = entity_id.split(".", 1)[-1].replace("_", "-")
            found.append({"id": f"ha-{slug}", "type": "rifiuti", "calendar": entity_id})
        return found

    def _ha_sources(self) -> list[dict[str, Any]]:
        """Each chosen Home Assistant calendar (not one of Family Hub's own) with its type and the
        persons it is for, as a source."""
        styles = self._entry.options.get("sources", {}).get("calendar_styles", {})
        found = []
        for entity_id, style in styles.items():
            # Family Hub's own calendars are found in the entity registry, whatever their names.
            registered = er.async_get(self._hass).async_get(entity_id)
            if registered is not None and registered.platform == DOMAIN:
                continue
            slug = entity_id.split(".", 1)[-1].replace("_", "-")
            found.append(
                {
                    "id": f"ha-{slug}",
                    "type": style.get("type") or "altro",
                    "calendar": entity_id,
                    "persons": list(style.get("persons", [])),
                }
            )
        return found

    async def async_day_lines(self, day: date) -> list[tuple[str, list[str]]]:
        """The lines of the linked calendars for one day's summary: each with the persons it is
        for (none: the whole family). Rubbish reads "Rifiuti: Organico" by its type, a holiday
        is one line ("Vacanze scuola") however many of its days are today, and other titles are
        listed as they are, in the family's language."""
        words = SUMMARY_TEXTS.get(self.language(), SUMMARY_TEXTS["en"])
        lines: list[tuple[str, list[str]]] = []
        for source in [*self.sources(), *self._ha_sources()]:
            kind = str(source.get("type") or "altro")
            names = await self._names_on(source, day)
            if not names:
                continue
            persons = [str(p) for p in source.get("persons", [])]
            if kind == "rifiuti":
                for name in names:
                    found = type_of(name, self.waste_types())
                    label = found["label"] if found else name
                    lines.append((f"{words['rubbish']}: {label}", persons))
            elif kind in VACATION_TYPES:
                lines.append((words[kind], persons))
            else:
                lines.extend((name, persons) for name in names)
        return lines

    async def _names_on(self, source: dict[str, Any], day: date) -> list[str]:
        """The titles of one source's events on a day: from the external file, or from the
        Home Assistant calendar the guide chose."""
        entity_id = source.get("calendar")
        if entity_id:
            return await self._ha_names_on(str(entity_id), day)
        calendar = self.entities.get(source["id"])
        if calendar is None or calendar.calendar is None:
            return []
        return [str(e.summary) for e in _on_day(calendar.calendar, day)]

    async def _ha_names_on(self, entity_id: str, day: date) -> list[str]:
        zone = dt_util.get_default_time_zone()
        start = datetime.combine(day, datetime.min.time(), zone)
        try:
            response = await self._hass.services.async_call(
                "calendar",
                "get_events",
                {
                    "entity_id": entity_id,
                    "start_date_time": start.isoformat(),
                    "end_date_time": (start + timedelta(days=1)).isoformat(),
                },
                blocking=True,
                return_response=True,
            )
        except HomeAssistantError as err:
            LOGGER.warning("Could not read the events of %s for a reminder: %s", entity_id, err)
            return []
        found = (response or {}).get(entity_id)
        events: Any = found.get("events", []) if isinstance(found, dict) else []
        if not isinstance(events, list):
            return []
        return [str(e["summary"]) for e in events if isinstance(e, dict) and e.get("summary")]

    @callback
    def async_stop(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()
        for unsub in self._snoozed.values():
            unsub()
        self._snoozed.clear()

    def _schedule_reminders(self, source: dict[str, Any]) -> None:
        """Evening (remind_at) and morning (morning_at) reminders for one source."""
        for key, kind in (("remind_at", "evening"), ("morning_at", "morning")):
            hh, mm = str(source.get(key) or ("19:00" if kind == "evening" else "07:00")).split(":")

            async def fire(_now: datetime, src: dict[str, Any] = source, kind: str = kind) -> None:
                await self.async_remind(src, kind)

            self._unsubs.append(
                async_track_time_change(self._hass, fire, hour=int(hh), minute=int(mm), second=0)
            )

    # ---- refresh ----

    async def _refresh_all(self, _now: datetime) -> None:
        for source in self.sources():
            if source.get("url"):
                await self.async_refresh(source["id"])

    async def async_refresh(self, source_id: str) -> None:
        """Download a link again. On failure the last valid copy stays."""
        source = next((s for s in self.sources() if s["id"] == source_id), None)
        if source is None or not source.get("url"):
            return
        now = dt_util.now().isoformat()
        try:
            text = await download(self._hass, source["url"])
            parse(text)
        except ExternalError as err:
            self.data["status"][source_id] = {**self.status(source_id), "error": err.code}
        else:
            self.data["contents"][source_id] = text
            self.data["status"][source_id] = {"updated": now, "error": None}
            self._apply(source_id)
        await self.async_save()

    async def async_set_content(self, source_id: str, text: str) -> None:
        """Store a new file (validated first). Used for uploads and for replacements."""
        parse(text)
        self.data["contents"][source_id] = text
        self.data["status"][source_id] = {"updated": dt_util.now().isoformat(), "error": None}
        self._apply(source_id)
        await self.async_save()

    @callback
    def _apply(self, source_id: str) -> None:
        entity = self.entities.get(source_id)
        if entity is not None:
            entity.set_content(self.content(source_id))

    async def async_forget(self, source_id: str) -> None:
        self.data["contents"].pop(source_id, None)
        self.data["status"].pop(source_id, None)
        await self.async_save()

    # ---- reminders ----

    async def async_remind(self, source: dict[str, Any], kind: str) -> None:
        """Send the reminders of one source for this moment: evening or morning."""
        text_for = TEXTS.get(self._entry.options.get(CONF_LANGUAGE, "en"), TEXTS["en"])
        today = dt_util.as_local(dt_util.now()).date()
        if source.get("type") == "rifiuti":
            # Rubbish: one reminder for all the pickups of the day, the evening before and the
            # morning of it. The uid is the pickup day, so "Fatto" closes both.
            pickup = today + timedelta(days=1) if kind == "evening" else today
            # The labels of the types ("Organico, Carta"), not the raw titles.
            names = labels_for(await self._names_on(source, pickup), self.waste_types())
            if not names:
                return
            label = text_for["tomorrow"] if kind == "evening" else text_for["today"]
            uid = f"{WASTE_UID_PREFIX}{source['id']}-{pickup.isoformat()}"
            await self._send(source, uid, f"{label}: {', '.join(names)}", text_for["title"], kind)
            return
        calendar = self.entities.get(source["id"])
        if calendar is None or calendar.calendar is None:
            return
        if source.get("return_notice") and kind == "evening":
            # Holidays: the evening before the day they end (the return).
            for event in _on_day(calendar.calendar, today):
                if event.end == today + timedelta(days=1):
                    uid = f"{WASTE_UID_PREFIX}{source['id']}-return-{today.isoformat()}"
                    await self._send(source, uid, text_for["return"], str(event.summary), kind)

    async def _send(
        self, source: dict[str, Any], uid: str, message: str, title: str, kind: str
    ) -> None:
        if uid in self.data["done"]:
            return
        # Kept, so that "Posticipa 1 ora" can send the same reminder again.
        self._pending[uid] = (source, uid, message, title)
        await self._post(source, uid, message, title)

    async def _post(self, source: dict[str, Any], uid: str, message: str, title: str) -> None:
        if uid in self.data["done"]:
            return
        lang = self._entry.options.get(CONF_LANGUAGE, "en")
        data = self._entry.runtime_data
        if data is None:
            return
        persons = source.get("persons") or [
            p["id"] for p in self._entry.options.get(OPT_PERSONS, [])
        ]
        reminders = self._entry.options.get(OPT_REMINDERS, {})
        targets = [t for t in data.reminders.targets_for(persons) if not t.quiet]
        actions = [
            {"action": f"FH_DONE_{uid}", "title": FATTO.get(lang, FATTO["en"])},
            {
                "action": f"FH_SNOOZE_{SNOOZE_MINUTES}_{uid}",
                "title": POSTICIPA.get(lang, POSTICIPA["en"]),
            },
        ]
        await async_send(
            self._hass,
            Delivery(
                title=title,
                message=message,
                notification_id=f"{DOMAIN}_{uid}",
                targets=targets,
                channels=frozenset(reminders.get("channels", [])),
                tts_entity=None,
                tablet=True,
                language=str(self._entry.options.get(CONF_LANGUAGE) or "en"),
                actions=actions,
                uid=uid,
            ),
        )

    # ---- "Fatto", "Posticipa 1 ora", "Ferma" (phone buttons, tablet popup, services) ----

    async def async_action(self, command: str, uid: str, minutes: int = SNOOZE_MINUTES) -> None:
        """Handle a reminder button for a rubbish or holiday reminder."""
        if command == "done":
            if uid not in self.data["done"]:
                self.data["done"].append(uid)
                await self.async_save()
            self._cancel_snooze(uid)
            await async_dismiss(self._hass, f"{DOMAIN}_{uid}", uid)
        elif command == "snooze":
            self._cancel_snooze(uid)

            async def again(_now: datetime, key: str = uid) -> None:
                self._snoozed.pop(key, None)
                pending = self._pending.get(key)
                if pending is not None:
                    await self._post(*pending)

            self._snoozed[uid] = async_track_point_in_time(
                self._hass, again, dt_util.now() + timedelta(minutes=minutes)
            )
        elif command == "dismiss":
            self._cancel_snooze(uid)
            await async_dismiss(self._hass, f"{DOMAIN}_{uid}", uid)

    def _cancel_snooze(self, uid: str) -> None:
        unsub = self._snoozed.pop(uid, None)
        if unsub is not None:
            unsub()


def is_waste_uid(uid: str) -> bool:
    return uid.startswith(WASTE_UID_PREFIX)


def action_from(parts: list[str]) -> tuple[str, str, int]:
    """Parse FH_DONE_<uid>, FH_DISMISS_<uid> or FH_SNOOZE_<minutes>_<uid> (uid has no "_")."""
    if parts[1] == "SNOOZE":
        return "snooze", parts[3], int(parts[2])
    if parts[1] == "DONE":
        return "done", parts[2], SNOOZE_MINUTES
    return "dismiss", parts[2], SNOOZE_MINUTES
