"""Reminders and day summaries, scheduled with Home Assistant timers (no polling).

* Timed events: one timer per moment = start minus the offsets (per event, or the family
  default). Moments are computed in absolute (UTC) time, so DST changes do not shift them.
* All-day events: a reminder the day before at a clock time (per event, per person, or the
  family default).
* Quiet hours: during a person's quiet window nothing reaches that person.
* Restart: a reminder that became due less than CATCH_UP ago, and was not sent yet, is sent
  again at start-up. Older ones are not. Sent reminders are marked in the event record.
* Morning and evening summaries at the configured times.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Coroutine
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.event import async_track_point_in_time, async_track_time_change
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ALEXA_VOLUME,
    CONF_ALL_DAY_REMINDER,
    CONF_CHANNELS,
    CONF_LANGUAGE,
    DEFAULT_REMINDERS,
    OPT_PERSONS,
    OPT_REMINDERS,
    PERSON_CHANNELS,
)
from .notifier import Delivery, Target, async_dismiss, async_send, reminder_actions, texts_for
from .weather import summary_line

if TYPE_CHECKING:
    from .models import FamilyHubConfigEntry
    from .storage import EventStore

LOGGER = logging.getLogger(__name__)
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
NOTIFICATION_PREFIX = "family_hub_"
CATCH_UP = timedelta(minutes=10)


def parse_hhmm(text: str | None) -> time | None:
    """Parse "HH:MM". Empty or None means not set."""
    if not text:
        return None
    match = _HHMM.match(text.strip())
    if match is None:
        raise ValueError(f"Expected HH:MM, got {text!r}")
    return time(int(match[1]), int(match[2]))


def _clock(value: Any) -> time | None:
    """Parse a stored HH:MM. An invalid value is ignored with a warning, never raised."""
    try:
        return parse_hhmm(value)
    except (ValueError, TypeError):
        LOGGER.warning("Ignoring invalid reminder time %r: expected HH:MM", value)
        return None


def in_quiet_hours(now: time, start: time | None, end: time | None) -> bool:
    """True inside [start, end). A window that crosses midnight (22:00-07:00) is supported."""
    if start is None or end is None or start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end


def timed_moments(start: datetime, offsets: list[int]) -> list[datetime]:
    """Reminder moments for a timed event, in absolute time (UTC), earliest first."""
    base = start.astimezone(dt_util.UTC)
    return sorted({base - timedelta(minutes=offset) for offset in offsets})


def reminder_times(start: datetime, offsets: list[int], now: datetime) -> list[datetime]:
    """Reminder moments that are still in the future, earliest first."""
    return [moment for moment in timed_moments(start, offsets) if moment > now]


def _mark(moment: datetime, only: str | None) -> str:
    """Identifies one reminder: its moment, and the person it is for (if any)."""
    return f"{moment.isoformat()}|{only or ''}"


def _tablet_allowed(targets: list[Target]) -> bool:
    """The wall-tablet popup is shared: it shows when someone it is for is awake and accepts
    the tablet channel. With nobody named, it shows."""
    return not targets or any(not t.quiet and "tablet" in t.channels for t in targets)


class ReminderManager:
    """Owns every reminder and summary timer of one Family Hub entry."""

    def __init__(self, hass: HomeAssistant, entry: FamilyHubConfigEntry, store: EventStore) -> None:
        self._hass = hass
        self._entry = entry
        self._store = store
        # (kind, uid, mark) -> cancel function. kind is "event" or "snooze".
        self._timers: dict[tuple[str, str, str], CALLBACK_TYPE] = {}
        self._unsubs: list[CALLBACK_TYPE] = []

    @property
    def settings(self) -> dict[str, Any]:
        """Family reminder settings, merged over the defaults."""
        return {**DEFAULT_REMINDERS, **self._entry.options.get(OPT_REMINDERS, {})}

    @property
    def _persons(self) -> dict[str, dict[str, Any]]:
        return {p["id"]: p for p in self._entry.options.get(OPT_PERSONS, [])}

    async def async_start(self) -> None:
        """Watch the store, schedule the summaries and catch up on reminders missed at restart."""
        self._unsubs.append(self._store.add_listener(self.async_refresh))
        for kind in ("morning", "evening"):
            clock = _clock(self.settings[f"{kind}_summary"])
            if clock is not None:
                self._unsubs.append(
                    async_track_time_change(
                        self._hass,
                        self._summary_action(kind),
                        hour=clock.hour,
                        minute=clock.minute,
                        second=0,
                    )
                )
        await self.async_refresh()
        await self._async_catch_up()

    def async_stop(self) -> None:
        """Cancel every timer and listener (on unload)."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for cancel in self._timers.values():
            cancel()
        self._timers.clear()

    async def async_refresh(self) -> None:
        """Rebuild the event reminders from the store. Snoozes are kept."""
        for key in [key for key in self._timers if key[0] == "event"]:
            self._timers.pop(key)()
        now = dt_util.now()
        for uid, record in self._store.events.items():
            if record.get("reminders_off"):
                continue
            sent = set(record.get("sent", []))
            for moment, only in self._record_moments(record):
                if moment > now and _mark(moment, only) not in sent:
                    self._schedule("event", uid, moment, only)

    async def _async_catch_up(self) -> None:
        """Send reminders that came due just before a restart and were not sent yet."""
        now = dt_util.now()
        for uid, record in list(self._store.events.items()):
            if record.get("reminders_off"):
                continue
            sent = set(record.get("sent", []))
            for moment, only in self._record_moments(record):
                if now - CATCH_UP < moment <= now and _mark(moment, only) not in sent:
                    await self.async_fire(uid, moment, only)

    def _record_moments(self, record: dict[str, Any]) -> list[tuple[datetime, str | None]]:
        """All reminder moments of an event: (moment, person id or None for everyone)."""
        settings = self.settings
        zone = dt_util.get_default_time_zone()
        if not record["all_day"]:
            offsets = record.get("reminder_offsets")
            if offsets is None:
                offsets = settings["offsets"]
            start = datetime.fromisoformat(record["start"])
            return [(moment, None) for moment in timed_moments(start, offsets)]

        start_date = date.fromisoformat(record["start"])
        moments: list[tuple[datetime, str | None]] = []
        person_ids: list[str | None] = [pid for pid in record.get("persons", [])] or [None]
        for person_id in person_ids:
            clock = self._all_day_clock(record, person_id)
            if clock is not None:
                day_before = start_date - timedelta(days=1)
                moments.append((datetime.combine(day_before, clock, tzinfo=zone), person_id))
        return moments

    def _all_day_clock(self, record: dict[str, Any], person_id: str | None) -> time | None:
        """Event setting first, then the person's, then the family default."""
        own_event = _clock(record.get(CONF_ALL_DAY_REMINDER))
        if own_event is not None:
            return own_event
        if person_id is not None:
            own_person = _clock(self._persons.get(person_id, {}).get(CONF_ALL_DAY_REMINDER))
            if own_person is not None:
                return own_person
        return _clock(self.settings["all_day_reminder"])

    def targets_for(self, person_ids: list[str]) -> list[Target]:
        """Resolve person ids to targets, with their quiet state right now."""
        settings = self.settings
        family_start = _clock(settings["quiet_start"])
        family_end = _clock(settings["quiet_end"])
        now = dt_util.as_local(dt_util.now()).time()
        targets: list[Target] = []
        for person_id in person_ids:
            person = self._persons.get(person_id)
            if person is None:
                continue
            own_start = _clock(person.get("quiet_start"))
            own_end = _clock(person.get("quiet_end"))
            start, end = (
                (own_start, own_end) if own_start and own_end else (family_start, family_end)
            )
            targets.append(
                Target(
                    name=person["name"],
                    phone_notify=person.get("phone_notify") or None,
                    speaker=person.get("speaker") or None,
                    alexa_notify=person.get("alexa_notify") or None,
                    quiet=in_quiet_hours(now, start, end),
                    channels=frozenset(person.get(CONF_CHANNELS, PERSON_CHANNELS)),
                    alexa_volume=person.get(CONF_ALEXA_VOLUME),
                )
            )
        return targets

    async def async_fire(
        self,
        uid: str,
        moment: datetime,
        only: str | None = None,
        *,
        mark_sent: bool = True,
    ) -> None:
        """Send one reminder if the event still exists, is not switched off, and is unsent."""
        record = self._store.events.get(uid)
        if record is None or record.get("reminders_off"):
            return
        mark = _mark(moment, only)
        if mark in record.get("sent", []):
            return
        settings = self.settings
        text = texts_for(self._entry.options.get(CONF_LANGUAGE, "en"))
        if record["all_day"]:
            message = f"{record['summary']} · {text['tomorrow']}"
        else:
            when = dt_util.as_local(datetime.fromisoformat(record["start"])).strftime("%H:%M")
            message = f"{when} · {record['summary']}"
        person_ids = [only] if only is not None else record.get("persons", [])
        targets = self.targets_for(person_ids)
        await async_send(
            self._hass,
            Delivery(
                title=text["reminder"],
                message=message,
                notification_id=f"{NOTIFICATION_PREFIX}{uid}",
                targets=[target for target in targets if not target.quiet],
                channels=frozenset(settings["channels"]),
                tts_entity=settings["tts_entity"],
                tablet=_tablet_allowed(targets),
                actions=reminder_actions(uid, text),
                uid=uid,
            ),
        )
        if mark_sent:
            record["sent"] = [*record.get("sent", []), mark]
            await self._store.async_save()

    async def _summary_message(
        self, kind: str, rows: list[tuple[datetime, str]], text: dict[str, str]
    ) -> str:
        """The summary text. The morning one starts with today's weather, if a weather entity
        was chosen in the guide."""
        lines = [line for _, line in rows]
        chosen = self._entry.options.get("sources", {}).get("weather", [])
        if kind == "morning" and chosen:
            weather = await summary_line(
                self._hass, chosen[0], self._entry.options.get(CONF_LANGUAGE, "en")
            )
            if weather:
                lines.insert(0, weather)
        return "\n".join(lines) or text["nothing"]

    async def async_send_summary(self, kind: str) -> None:
        """Send the morning ("today") or evening ("tomorrow") summary to everyone."""
        now = dt_util.as_local(dt_util.now())
        day = now.date() if kind == "morning" else now.date() + timedelta(days=1)
        text = texts_for(self._entry.options.get(CONF_LANGUAGE, "en"))
        names = {pid: person["name"] for pid, person in self._persons.items()}

        rows: list[tuple[datetime, str]] = []
        for record in self._store.events.values():
            if record["all_day"]:
                start_date = datetime.fromisoformat(record["start"]).date()
                key = datetime.combine(start_date, time.min, tzinfo=now.tzinfo)
                label = text["all_day"]
            else:
                key = dt_util.as_local(datetime.fromisoformat(record["start"]))
                start_date = key.date()
                label = key.strftime("%H:%M")
            if start_date != day:
                continue
            who = ", ".join(names[pid] for pid in record.get("persons", []) if pid in names)
            line = f"{label}  {record['summary']}" + (f" ({who})" if who else "")
            rows.append((key, line))

        rows.sort(key=lambda row: row[0])
        targets = self.targets_for(list(names))
        title = text["summary_morning"] if kind == "morning" else text["summary_evening"]
        await async_send(
            self._hass,
            Delivery(
                title=title,
                message=await self._summary_message(kind, rows, text),
                notification_id=f"{NOTIFICATION_PREFIX}summary_{kind}",
                targets=[target for target in targets if not target.quiet],
                channels=frozenset(self.settings["channels"]),
                tts_entity=None,
                tablet=_tablet_allowed(targets),
            ),
        )

    async def async_handle_action(self, action: str) -> None:
        """Handle a phone button: FH_DONE_<uid>, FH_DISMISS_<uid>, FH_SNOOZE_<minutes>_<uid>."""
        parts = action.split("_")
        try:
            command = parts[1]
            if command == "SNOOZE":
                await self.async_snooze(parts[3], int(parts[2]))
            elif command == "DONE":
                await self.async_stop_event(parts[2])
            elif command == "DISMISS":
                await self.async_dismiss(parts[2])
            else:
                LOGGER.warning("Unknown reminder action %s", parts[1])
        except (IndexError, ValueError):
            LOGGER.warning("Malformed reminder action")

    async def async_snooze(self, uid: str, minutes: int) -> None:
        """Remind again in ``minutes``. The event must exist."""
        if uid not in self._store.events:
            return
        self._schedule("snooze", uid, dt_util.now() + timedelta(minutes=minutes))

    async def async_dismiss(self, uid: str) -> None:
        """Remove this reminder's popup and cancel its snoozes. Later reminders still come."""
        self._cancel(uid, "snooze")
        await async_dismiss(self._hass, f"{NOTIFICATION_PREFIX}{uid}", uid)

    async def async_stop_event(self, uid: str) -> None:
        """Stop every reminder of an event ("Fatto" or the stop_reminder action)."""
        record = self._store.events.get(uid)
        if record is None:
            return
        record["reminders_off"] = True
        self._cancel(uid)
        await self._store.async_save()
        await async_dismiss(self._hass, f"{NOTIFICATION_PREFIX}{uid}", uid)

    def _cancel(self, uid: str, kind: str | None = None) -> None:
        for key in [key for key in self._timers if key[1] == uid and kind in (None, key[0])]:
            self._timers.pop(key)()

    def _schedule(self, kind: str, uid: str, moment: datetime, only: str | None = None) -> None:
        key = (kind, uid, _mark(moment, only))
        if key not in self._timers:
            self._timers[key] = async_track_point_in_time(
                self._hass,
                self._timer_action(kind, key, uid, moment, only),
                moment,
            )

    def _timer_action(
        self,
        kind: str,
        key: tuple[str, str, str],
        uid: str,
        moment: datetime,
        only: str | None,
    ) -> Callable[[datetime], Coroutine[Any, Any, None]]:
        async def _fire(_now: datetime) -> None:
            self._timers.pop(key, None)
            await self.async_fire(uid, moment, only, mark_sent=kind == "event")

        return _fire

    def _summary_action(self, kind: str) -> Callable[[datetime], Coroutine[Any, Any, None]]:
        async def _send(_now: datetime) -> None:
            await self.async_send_summary(kind)

        return _send
