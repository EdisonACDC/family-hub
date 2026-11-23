"""Invites for people without a Home Assistant account (for example the grandparents).

An adult makes an invite: a name, the persons and calendars it may see, what it may do. The
invite is a link to the guest web app (served by guest_http.py) with a random token in the
fragment. One phone opens it and becomes a device, waiting until an adult confirms it.

Security rules kept here:

* Invite and device tokens are random (256 bits) and kept only as SHA-256 hashes, compared in
  constant time. A token is never logged, stored in clear or put in a URL by the server.
* What a guest sees is filtered here, on the server, every time: only the chosen persons and
  calendars, and only the fields the web app needs. Nothing else of Home Assistant.
* A device that is disabled, rejected or still waiting gets nothing, at once.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re
import secrets
import time as monotime
import uuid
from collections import deque
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_point_in_time, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from . import guest_features as gf
from . import webpush
from .const import (
    CONF_FIRST_WEEKDAY,
    CONF_LANGUAGE,
    CONF_THEME,
    CONF_TIME_FORMAT,
    CONF_WEEK_FROM_TODAY,
    DEFAULT_REMINDERS,
    DOMAIN,
    OPT_CATEGORIES,
    OPT_PERSONS,
    OPT_REMINDERS,
    OPT_SHIFTS,
)
from .shifts import ShiftError, clean_shifts
from .storage import event_version

if TYPE_CHECKING:
    from .calendar import FamilyHubCalendar
    from .models import FamilyHubConfigEntry
    from .storage import EventStore

LOGGER = logging.getLogger(__name__)

GUEST_STORAGE_VERSION = 1
# What a device may do.
VIEW = "view"
ADD = "add"
EDIT_OWN = "edit_own"
PERMISSIONS = (VIEW, ADD, EDIT_OWN)
# Where an appointment added by a guest goes.
APPROVE = "approve"
DIRECT = "direct"
APPROVALS = (APPROVE, DIRECT)
# Device states.
PENDING = "pending"
ACTIVE = "active"
REJECTED = "rejected"
DISABLED = "disabled"
# Invite states.
OPEN = "open"
USED = "used"
REVOKED = "revoked"
EXPIRED = "expired"

DEFAULT_EXPIRY_DAYS = 7
MAX_EXPIRY_DAYS = 30
TOKEN_BYTES = 32  # 256 bits
ROTATE_AFTER = timedelta(days=30)
# The old token still works for a while after a rotation, so a phone that missed the answer
# is not locked out.
ROTATE_GRACE = timedelta(days=7)
LOG_SIZE = 200
MAX_NAME = 40
MAX_TITLE = 80
MAX_LOCATION = 100
MAX_NOTE = 500
MAX_RANGE_DAYS = 62
# A guest may add appointments from yesterday to two years ahead.
PAST_DAYS = 1
FUTURE_DAYS = 731
# More changes than this at once (a series rewritten) give one message instead of many.
MAX_CHANGE_PUSHES = 3
ACTION_PREFIX = "FH_GUEST_"
ATTEMPT_NOTICE_SECONDS = 600
# Invites that are used, expired or cancelled go away by themselves after this long.
INVITE_KEEP = timedelta(days=30)
CLEANUP_EVERY = timedelta(hours=6)
# Reminders of phones with their own minutes are planned this far ahead, again every hour.
OWN_REMINDERS_AHEAD = timedelta(hours=49)
OWN_REMINDERS_EVERY = timedelta(hours=1)
MAX_OWN_OFFSETS = 5
# New appointments for a guest: collected for this long, then one message (or one summary).
NEW_BATCH = timedelta(minutes=2)
# A guest's shifts: at most this many days at once, and a rotation of at most this many steps.
MAX_SHIFT_DAYS = 62
MAX_ROTATION = 28
DEFAULT_SHIFT_COLOR = "#8B5CF6"
_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
TEST_PUSH_EVERY = 60.0
# The notification status of a phone, as the adults see it.
PUSH_ACTIVE = "active"
PUSH_OFF = "off"
PUSH_BLOCKED = "blocked"
# Who gets the requests (a phone opened an invite, an appointment to approve).
RECIPIENTS_ADULTS = "adults"
RECIPIENTS_PERSONS = "persons"
RECIPIENT_MODES = (RECIPIENTS_ADULTS, RECIPIENTS_PERSONS)

_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ID = re.compile(r"^[0-9a-f]{32}$")

TEXTS: dict[str, dict[str, str]] = {
    "it": {
        "title": "Family Hub",
        "device_waiting": "Un telefono ({label}) ha aperto l'invito «{name}». Confermi?",
        "device_waiting_tablet": (
            "Un telefono ({label}) ha aperto l'invito «{name}». Per confermarlo o rifiutarlo "
            "apri Family Hub → ☰ → Condivisione → Dispositivi."
        ),
        "confirm": "Conferma",
        "reject": "Rifiuta",
        "approve": "Approva",
        "decline": "Rifiuta",
        "to_approve": "{name} ha aggiunto «{title}» ({when}). Approvi?",
        "to_approve_tablet": (
            "{name} ha aggiunto «{title}» ({when}). Apri Family Hub per approvare o rifiutare."
        ),
        "approved": "Approvato: {title} ({when})",
        "declined": "Non approvato: {title} ({when})",
        "changed": "Modificato: {title} ({when})",
        "cancelled": "Annullato: {title} ({when})",
        "many_changes": "Alcuni appuntamenti sono cambiati. Apri Family Hub per vederli.",
        "new_one": "Nuovo impegno per {who}: {title}, {when}",
        "new_one_family": "Nuovo impegno: {title}, {when}",
        "new_many": "{n} nuovi impegni per {who}",
        "new_many_family": "{n} nuovi impegni",
        "and": " e ",
        "at": "ore",
        "days": "lun mar mer gio ven sab dom",
        "shifts_week": "{name} ha aggiornato i turni della prossima settimana",
        "shifts_range": "{name} ha aggiornato i turni dal {first} al {last}",
        "shifts_types": "{name} ha aggiornato i suoi tipi di turno",
        "reminder": "Promemoria",
        "test_push": "Prova: le notifiche di Family Hub arrivano su questo telefono.",
        "all_day": "tutto il giorno",
        "tomorrow": "domani",
        "attempt_used": (
            "Qualcuno ha provato ad aprire di nuovo l'invito «{name}», già usato ({label}). "
            "L'accesso è stato negato."
        ),
        "attempt_expired": (
            "Qualcuno ha provato ad aprire l'invito «{name}», scaduto ({label}). "
            "L'accesso è stato negato."
        ),
        "attempt_revoked": (
            "Qualcuno ha provato ad aprire l'invito «{name}», annullato ({label}). "
            "L'accesso è stato negato."
        ),
    },
    "de": {
        "title": "Family Hub",
        "device_waiting": "Ein Telefon ({label}) hat die Einladung «{name}» geöffnet. Bestätigen?",
        "device_waiting_tablet": (
            "Ein Telefon ({label}) hat die Einladung «{name}» geöffnet. Zum Bestätigen oder "
            "Ablehnen Family Hub öffnen → ☰ → Teilen → Geräte."
        ),
        "confirm": "Bestätigen",
        "reject": "Ablehnen",
        "approve": "Annehmen",
        "decline": "Ablehnen",
        "to_approve": "{name} hat «{title}» ({when}) eingetragen. Annehmen?",
        "to_approve_tablet": (
            "{name} hat «{title}» ({when}) eingetragen. Zum Annehmen oder Ablehnen Family Hub "
            "öffnen."
        ),
        "approved": "Angenommen: {title} ({when})",
        "declined": "Nicht angenommen: {title} ({when})",
        "changed": "Geändert: {title} ({when})",
        "cancelled": "Abgesagt: {title} ({when})",
        "many_changes": "Einige Termine haben sich geändert. Family Hub öffnen, um sie zu sehen.",
        "new_one": "Neuer Termin für {who}: {title}, {when}",
        "new_one_family": "Neuer Termin: {title}, {when}",
        "new_many": "{n} neue Termine für {who}",
        "new_many_family": "{n} neue Termine",
        "and": " und ",
        "at": "um",
        "days": "Mo Di Mi Do Fr Sa So",
        "shifts_week": "{name} hat die Schichten der nächsten Woche aktualisiert",
        "shifts_range": "{name} hat die Schichten vom {first} bis {last} aktualisiert",
        "shifts_types": "{name} hat die eigenen Schichtarten aktualisiert",
        "reminder": "Erinnerung",
        "test_push": "Test: Mitteilungen von Family Hub kommen auf diesem Telefon an.",
        "all_day": "ganztägig",
        "tomorrow": "morgen",
        "attempt_used": (
            "Jemand hat versucht, die schon benutzte Einladung «{name}» erneut zu öffnen "
            "({label}). Der Zugang wurde verweigert."
        ),
        "attempt_expired": (
            "Jemand hat versucht, die abgelaufene Einladung «{name}» zu öffnen ({label}). "
            "Der Zugang wurde verweigert."
        ),
        "attempt_revoked": (
            "Jemand hat versucht, die zurückgezogene Einladung «{name}» zu öffnen ({label}). "
            "Der Zugang wurde verweigert."
        ),
    },
    "en": {
        "title": "Family Hub",
        "device_waiting": "A phone ({label}) opened the invite “{name}”. Confirm it?",
        "device_waiting_tablet": (
            "A phone ({label}) opened the invite “{name}”. To confirm or reject it, open "
            "Family Hub → ☰ → Sharing → Devices."
        ),
        "confirm": "Confirm",
        "reject": "Reject",
        "approve": "Approve",
        "decline": "Reject",
        "to_approve": "{name} added “{title}” ({when}). Approve it?",
        "to_approve_tablet": (
            "{name} added “{title}” ({when}). Open Family Hub to approve or reject."
        ),
        "approved": "Approved: {title} ({when})",
        "declined": "Not approved: {title} ({when})",
        "changed": "Changed: {title} ({when})",
        "cancelled": "Cancelled: {title} ({when})",
        "many_changes": "Some appointments changed. Open Family Hub to see them.",
        "new_one": "New appointment for {who}: {title}, {when}",
        "new_one_family": "New appointment: {title}, {when}",
        "new_many": "{n} new appointments for {who}",
        "new_many_family": "{n} new appointments",
        "and": " and ",
        "at": "at",
        "days": "Mon Tue Wed Thu Fri Sat Sun",
        "shifts_week": "{name} updated the shifts of the coming week",
        "shifts_range": "{name} updated the shifts from {first} to {last}",
        "shifts_types": "{name} updated their shift types",
        "reminder": "Reminder",
        "test_push": "Test: Family Hub notifications reach this phone.",
        "all_day": "all day",
        "tomorrow": "tomorrow",
        "attempt_used": (
            "Someone tried to open the invite “{name}” again, but it was already used ({label}). "
            "Access was refused."
        ),
        "attempt_expired": (
            "Someone tried to open the invite “{name}”, which has expired ({label}). "
            "Access was refused."
        ),
        "attempt_revoked": (
            "Someone tried to open the invite “{name}”, which was cancelled ({label}). "
            "Access was refused."
        ),
    },
}


class GuestError(Exception):
    """A guest request that is refused. ``code`` is all the web app is told."""

    def __init__(self, code: str, status: int = 403) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def new_token() -> str:
    """A random token of 256 bits, safe in a URL fragment."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_hash(token: str) -> str:
    """The only form in which a token is kept."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def same_hash(stored: str | None, candidate: str) -> bool:
    """Constant-time comparison of two hashes."""
    return bool(stored) and hmac.compare_digest(str(stored), candidate)


def texts_for(language: str) -> dict[str, str]:
    return TEXTS.get(language, TEXTS["en"])


def describe_device(user_agent: str) -> str:
    """A short description of a phone from its browser: "Android · Chrome", "iPhone · Safari".
    Worked out on the server; nothing the page says about itself is used."""
    agent = user_agent or ""
    if "iPhone" in agent:
        system = "iPhone"
    elif "iPad" in agent:
        system = "iPad"
    elif "Android" in agent:
        system = "Android"
    elif "Windows" in agent:
        system = "Windows"
    elif "Mac OS X" in agent or "Macintosh" in agent:
        system = "Mac"
    elif "Linux" in agent:
        system = "Linux"
    else:
        system = "?"
    if "SamsungBrowser" in agent:
        browser = "Samsung Internet"
    elif "Edg" in agent:
        browser = "Edge"
    elif "Firefox" in agent or "FxiOS" in agent:
        browser = "Firefox"
    elif "OPR/" in agent or "Opera" in agent:
        browser = "Opera"
    elif "Chrome" in agent or "CriOS" in agent:
        browser = "Chrome"
    elif "Safari" in agent:
        browser = "Safari"
    else:
        browser = "Browser"
    return f"{system} · {browser}"


class RateLimiter:
    """At most ``limit`` hits per ``window`` seconds for each key (a device or an address)."""

    def __init__(self, limit: int, window: float = 60.0) -> None:
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        now = monotime.monotonic() if now is None else now
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        if len(self._hits) > 5000:  # forget idle keys
            for old in [k for k, v in self._hits.items() if not v]:
                del self._hits[old]
        return True


class ActivationGuard:
    """Blocks an address for a while after too many failed activations."""

    def __init__(self, attempts: int = 10, block_seconds: float = 900.0) -> None:
        self.attempts = attempts
        self.block_seconds = block_seconds
        self._failures: dict[str, list[float]] = {}
        self._blocked: dict[str, float] = {}

    def blocked(self, address: str, now: float | None = None) -> bool:
        now = monotime.monotonic() if now is None else now
        until = self._blocked.get(address)
        if until is None:
            return False
        if now >= until:
            del self._blocked[address]
            self._failures.pop(address, None)
            return False
        return True

    def failed(self, address: str, now: float | None = None) -> None:
        now = monotime.monotonic() if now is None else now
        recent = [t for t in self._failures.get(address, []) if t > now - self.block_seconds]
        recent.append(now)
        self._failures[address] = recent
        if len(recent) >= self.attempts:
            self._blocked[address] = now + self.block_seconds


def _now() -> datetime:
    return dt_util.utcnow()


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _text(value: Any, max_len: int, *, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise GuestError("invalid", 422)
    text = " ".join(value.split()) if max_len <= MAX_LOCATION else value.strip()
    if required and not text:
        raise GuestError("invalid", 422)
    if len(text) > max_len:
        raise GuestError("invalid", 422)
    return text


def _clock(value: Any) -> time:
    if not isinstance(value, str) or not _HHMM.match(value):
        raise GuestError("invalid", 422)
    return time(int(value[:2]), int(value[3:]))


def _day(value: Any) -> date:
    if not isinstance(value, str) or not _DAY.match(value):
        raise GuestError("invalid", 422)
    try:
        return date.fromisoformat(value)
    except ValueError as err:
        raise GuestError("invalid", 422) from err


MAX_EXTERNAL_EVENTS = 500


def _moment(value: Any) -> date | datetime:
    """A day ("2026-11-17") or a moment, as Home Assistant's calendar service gives them."""
    text = str(value)
    return date.fromisoformat(text) if len(text) == 10 else datetime.fromisoformat(text)


_VERSION = re.compile(r"^[0-9a-f]{6,40}$")

EVENT_KEYS = {"title", "person", "category", "date", "all_day", "start", "end", "location", "note"}


MAX_CHOSEN = 50


def _slot_value(item: dict[str, Any]) -> tuple[date | datetime, date | datetime]:
    """A checked chosen date (see clean_event) as the calendar takes it."""
    if item["all_day"]:
        return date.fromisoformat(item["start"]), date.fromisoformat(item["end"])
    return datetime.fromisoformat(item["start"]), datetime.fromisoformat(item["end"])


def _times(event: dict[str, Any]) -> dict[str, Any]:
    """The start and end of a checked appointment, as the calendar's change takes them."""
    if event["all_day"]:
        return {
            "dtstart": date.fromisoformat(event["start"]),
            "dtend": date.fromisoformat(event["end"]),
        }
    return {
        "dtstart": datetime.fromisoformat(event["start"]),
        "dtend": datetime.fromisoformat(event["end"]),
    }


def clean_chosen(
    raw: dict[str, Any],
    persons: list[str],
    categories: list[str],
    today: date,
    *,
    any_date: bool = False,
) -> dict[str, Any]:
    """An appointment on chosen dates: the fields of one appointment, and "dates" (up to 50), each
    with its own date, and its own start and end. Each date is checked as one appointment is. The
    result has the first date's start, end and all_day, and the list in time order (no repeats)."""
    if set(raw) - (EVENT_KEYS | {"dates"}) or set(raw) & {"date", "start", "end", "all_day"}:
        raise GuestError("invalid", 422)
    items = raw["dates"]
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_CHOSEN:
        raise GuestError("invalid", 422)
    common: dict[str, Any] = {
        key: raw[key] for key in ("title", "person", "category", "location", "note") if key in raw
    }
    checked: dict[str, dict[str, Any]] = {}
    for item in items:
        if (
            not isinstance(item, dict)
            or "date" not in item
            or set(item) - {"date", "start", "end", "all_day"}
        ):
            raise GuestError("invalid", 422)
        one: dict[str, Any] = {
            **common,
            "date": item["date"],
            "all_day": item.get("all_day", False),
        }
        if "start" in item:
            one["start"] = item["start"]
        if "end" in item:
            one["end"] = item["end"]
        event = clean_event(one, persons, categories, today, any_date=any_date)
        checked.setdefault(event["start"], event)
    slots = sorted(checked.values(), key=lambda event: event["start"])
    result = dict(slots[0])
    result["dates"] = [
        {"start": event["start"], "end": event["end"], "all_day": event["all_day"]}
        for event in slots
    ]
    return result


def clean_event(
    raw: Any,
    persons: list[str],
    categories: list[str],
    today: date,
    *,
    any_date: bool = False,
) -> dict[str, Any]:
    """An appointment sent by the web app, checked field by field. Anything else is refused.

    The result is a stored appointment (see EventStore) without uid and category times in the
    local zone: summary, category, persons, start, end, all_day, location, description. With
    "dates" (chosen dates, see clean_chosen) the result also has the list of dates.
    """
    if isinstance(raw, dict) and "dates" in raw:
        return clean_chosen(raw, persons, categories, today, any_date=any_date)
    if not isinstance(raw, dict) or set(raw) - EVENT_KEYS:
        raise GuestError("invalid", 422)
    title = _text(raw.get("title"), MAX_TITLE, required=True)
    person = raw.get("person")
    category = raw.get("category")
    if not isinstance(person, str) or person not in persons:
        raise GuestError("forbidden", 403)
    if not isinstance(category, str) or category not in categories:
        raise GuestError("forbidden", 403)
    day = _day(raw.get("date"))
    if not any_date and not (
        today - timedelta(days=PAST_DAYS) <= day <= today + timedelta(days=FUTURE_DAYS)
    ):
        # Its own code, so the web app can say which days are allowed (not just "invalid").
        raise GuestError("date_range", 422)
    all_day = raw.get("all_day", False)
    if not isinstance(all_day, bool):
        raise GuestError("invalid", 422)
    zone = dt_util.get_default_time_zone()
    if all_day:
        # Times are not used for a whole day, but what is sent must still be a time.
        for key in ("start", "end"):
            if key in raw:
                _clock(raw[key])
        start_text = day.isoformat()
        end_text = (day + timedelta(days=1)).isoformat()
    else:
        start = datetime.combine(day, _clock(raw.get("start")), tzinfo=zone)
        end = datetime.combine(day, _clock(raw.get("end")), tzinfo=zone)
        if end <= start:
            raise GuestError("invalid", 422)
        start_text, end_text = start.isoformat(), end.isoformat()
    return {
        "summary": title,
        "category": category,
        "persons": [person],
        "start": start_text,
        "end": end_text,
        "all_day": all_day,
        "location": _text(raw.get("location"), MAX_LOCATION),
        "description": _text(raw.get("note"), MAX_NOTE),
    }


class GuestHub:
    """The guest managers of every loaded Family Hub entry, for the web app's views (which are
    shared by all entries). Lives in hass.data[DOMAIN]["guests"]."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.managers: dict[str, GuestManager] = {}
        self.views_registered = False
        self.read_limit = RateLimiter(60)
        self.write_limit = RateLimiter(10)
        self.activation = ActivationGuard()

    def enabled(self) -> bool:
        """The web app answers only while a family has an open invite or a device."""
        return any(manager.in_use() for manager in self.managers.values())

    def ensure_views(self) -> None:
        """Register the web app's views the first time an invite or a device exists. A family
        that never makes an invite has no new address in Home Assistant."""
        if self.views_registered:
            return
        from .guest_http import register_views  # noqa: PLC0415

        register_views(self.hass)
        self.views_registered = True

    def device_for(self, token: str) -> tuple[GuestManager, dict[str, Any]] | None:
        digest = token_hash(token)
        for manager in self.managers.values():
            device = manager.device_by_hash(digest)
            if device is not None:
                return manager, device
        return None

    def invite_for(self, token: str) -> tuple[GuestManager, dict[str, Any]] | None:
        digest = token_hash(token)
        for manager in self.managers.values():
            invite = manager.invite_by_hash(digest)
            if invite is not None:
                return manager, invite
        return None


@callback
def guest_hub(hass: HomeAssistant) -> GuestHub:
    data = hass.data.setdefault(DOMAIN, {})
    hub = data.get("guests")
    if hub is None:
        hub = data["guests"] = GuestHub(hass)
    return hub  # type: ignore[no-any-return]


class GuestManager:
    """Invites, devices, the approval queue and the activity log of one Family Hub entry."""

    def __init__(self, hass: HomeAssistant, entry: FamilyHubConfigEntry, store: EventStore) -> None:
        self.hass = hass
        self.entry = entry
        self.events = store
        self._store: Store[dict[str, Any]] = Store(
            hass, GUEST_STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.guests", private=True
        )
        self.invites: dict[str, dict[str, Any]] = {}
        self.devices: dict[str, dict[str, Any]] = {}
        self.pending: dict[str, dict[str, Any]] = {}
        self.log: list[dict[str, Any]] = []
        self.vapid: dict[str, str] = {}
        # What each appointment looked like at the last save, to tell guests about changes.
        self._snapshot: dict[str, tuple[Any, ...]] | None = None
        self._snapshot_records: dict[str, dict[str, Any]] = {}
        # The device making a change right now: it is not told about its own change.
        self._changing: str | None = None
        self._reminded: dict[str, float] = {}
        # When the adults were last told about a refused try, per invite.
        self._attempt_told: dict[str, float] = {}
        # Who gets the requests: the adults with a phone, or chosen persons. Without any phone
        # among them, Home Assistant's administrators who have the Companion app.
        self.recipients: dict[str, Any] = {"mode": RECIPIENTS_ADULTS, "persons": []}
        # Where Family Hub opens in Home Assistant (told by the add-on), for a tapped notification.
        self.panel = ""
        self._unsub_cleanup: Callable[[], None] | None = None
        self._unsub_own: Callable[[], None] | None = None
        # Reminders of phones with their own minutes: (device, uid, moment) -> cancel.
        self._own_timers: dict[tuple[str, str, str], Callable[[], None]] = {}
        self._own_sent: set[tuple[str, str, str]] = set()
        self._test_sent: dict[str, float] = {}
        # New appointments waiting to be told, per device, and the timer that tells them.
        self._new_queue: dict[str, list[str]] = {}
        self._new_timers: dict[str, Callable[[], None]] = {}
        # The guests' shift changes, told to the adults a little later.
        self._shift_notices: dict[str, dict[str, Any]] = {}
        self._shift_timers: dict[str, Callable[[], None]] = {}
        self._tasks: set[asyncio.Task[Any]] = set()

    # ----- storage --------------------------------------------------------

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if data:
            self.invites = dict(data.get("invites", {}))
            self.devices = dict(data.get("devices", {}))
            self.pending = dict(data.get("pending", {}))
            self.log = list(data.get("log", []))[-LOG_SIZE:]
            self.vapid = dict(data.get("vapid", {}))
            self.recipients = dict(data.get("recipients") or self.recipients)
            self.panel = str(data.get("panel") or "")
        # Invites and phones of 0.9: the "Nonni" template with the permissions they have.
        upgraded = [gf.upgrade(i) for i in [*self.invites.values(), *self.devices.values()]]
        if self._cleanup_invites() or any(upgraded):
            await self._store.async_save(self._data())

        async def _cleanup(_now: datetime) -> None:
            if self._cleanup_invites():
                await self.async_save()

        self._unsub_cleanup = async_track_time_interval(self.hass, _cleanup, CLEANUP_EVERY)

        async def _plan(_now: datetime) -> None:
            self._plan_own_reminders()

        self._unsub_own = async_track_time_interval(self.hass, _plan, OWN_REMINDERS_EVERY)
        self._plan_own_reminders()
        if self.in_use():
            guest_hub(self.hass).ensure_views()
        self._ensure_snapshot()

    def _data(self) -> dict[str, Any]:
        return {
            "invites": self.invites,
            "devices": self.devices,
            "pending": self.pending,
            "log": self.log,
            "vapid": self.vapid,
            "recipients": self.recipients,
            "panel": self.panel,
        }

    async def async_save(self) -> None:
        await self._store.async_save(self._data())
        self.hass.bus.async_fire(f"{DOMAIN}_guest_changed", {"entry_id": self.entry.entry_id})

    def _save_later(self) -> None:
        """For "last seen": written within a minute, not on every request."""
        self._store.async_delay_save(self._data, 60)

    def in_use(self) -> bool:
        now = _now()
        if any(self._invite_open(invite, now) for invite in self.invites.values()):
            return True
        return any(d["status"] in (PENDING, ACTIVE) for d in self.devices.values())

    def _record(self, kind: str, name: str, detail: str = "") -> None:
        self.log.append({"at": _iso(_now()), "kind": kind, "name": name, "detail": detail})
        del self.log[:-LOG_SIZE]

    # ----- family data ----------------------------------------------------

    @property
    def language(self) -> str:
        return str(self.entry.options.get(CONF_LANGUAGE) or "en")

    def _persons(self) -> dict[str, dict[str, Any]]:
        return {str(p["id"]): p for p in self.entry.options.get(OPT_PERSONS, [])}

    def _categories(self) -> dict[str, dict[str, Any]]:
        return {str(c["id"]): c for c in self.entry.options.get(OPT_CATEGORIES, [])}

    def _calendar(self, category_id: str) -> FamilyHubCalendar:
        calendar = self.entry.runtime_data.calendars.get(category_id)
        if calendar is None:
            raise GuestError("forbidden", 403)
        return calendar

    # ----- invites (adults) -------------------------------------------------

    @staticmethod
    def _invite_open(invite: dict[str, Any], now: datetime) -> bool:
        expires = _parse(invite.get("expires_at"))
        return invite.get("status") == OPEN and expires is not None and expires > now

    def clean_scope(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Persons, calendars and permissions of an invite or a device, checked against the
        family's own lists."""
        persons = raw.get("persons")
        categories = raw.get("categories")
        known_persons = self._persons()
        known_categories = self._categories()
        if (
            not isinstance(persons, list)
            or not persons
            or not all(isinstance(p, str) and p in known_persons for p in persons)
        ):
            raise GuestError("invalid_persons", 422)
        if (
            not isinstance(categories, list)
            or not categories
            or not all(isinstance(c, str) and c in known_categories for c in categories)
        ):
            raise GuestError("invalid_categories", 422)
        # A template fills what the adult left out; a 0.9 request keeps the old defaults.
        defaults, _legacy = gf.defaults_for(raw)
        permission = raw.get("permission", defaults["permission"])
        approval = raw.get("approval", defaults["approval"])
        notify = raw.get("notify", defaults["notify"])
        family_events = raw.get("family_events", defaults["family_events"])
        if permission not in PERMISSIONS or approval not in APPROVALS:
            raise GuestError("invalid", 422)
        if not isinstance(notify, bool) or not isinstance(family_events, bool):
            raise GuestError("invalid", 422)
        has_shifts = raw.get("has_shifts", defaults["has_shifts"])
        shift_color = raw.get("shift_color") or DEFAULT_SHIFT_COLOR
        shifts_category = raw.get("shifts_category") or next(iter(known_categories), "")
        if not isinstance(has_shifts, bool) or not isinstance(shift_color, str):
            raise GuestError("invalid", 422)
        if not _COLOR.match(shift_color) or shifts_category not in known_categories:
            raise GuestError("invalid", 422)
        # Whose shifts they are: "" a guest person of its own, or a person of the family (who
        # must be among the persons the guest sees: linking her gives no one else's appointments).
        shifts_person = raw.get("shifts_person") or ""
        if not isinstance(shifts_person, str):
            raise GuestError("invalid", 422)
        if not has_shifts:
            shifts_person = ""
        if shifts_person and (shifts_person not in known_persons or shifts_person not in persons):
            raise GuestError("invalid_shifts_person", 422)
        # Mode, template, the functions it may use and the lists it may open.
        extra = gf.clean(raw, gf.family_lists(self.entry.options), list(self.externals()))
        if extra is None:
            raise GuestError("invalid", 422)
        return {
            **extra,
            "persons": list(dict.fromkeys(persons)),
            "categories": list(dict.fromkeys(categories)),
            "permission": permission,
            "approval": approval,
            "notify": notify,
            # Also the appointments of the whole family (no person) in the chosen calendars.
            "family_events": family_events,
            # The guest's own work shifts: a guest person of the family, with its colour, and the
            # calendar its shifts go to.
            "has_shifts": has_shifts,
            "shift_color": shift_color,
            "shifts_category": shifts_category,
            "shifts_person": shifts_person,
        }

    async def async_create_invite(self, raw: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """A new invite. Returns it and its token: the token is shown once and never kept."""
        name = _text(raw.get("name"), MAX_NAME, required=True)
        scope = self.clean_scope(raw)
        days = raw.get("expires_days", DEFAULT_EXPIRY_DAYS)
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= MAX_EXPIRY_DAYS:
            raise GuestError("invalid", 422)
        invite, token = await self._new_invite(name, scope, days)
        self._record("invite_created", name)
        await self.async_save()
        guest_hub(self.hass).ensure_views()
        return invite, token

    async def _new_invite(
        self, name: str, scope: dict[str, Any], days: int, replaces: str | None = None
    ) -> tuple[dict[str, Any], str]:
        token = new_token()
        now = _now()
        invite = {
            "id": uuid.uuid4().hex,
            "name": name,
            **scope,
            "created_at": _iso(now),
            "expires_at": _iso(now + timedelta(days=days)),
            "status": OPEN,
            "token_hash": token_hash(token),
            "device_id": None,
            "closed_at": None,
            # "Nuovo telefono": the device this invite's phone will take the place of.
            "replaces": replaces,
        }
        self.invites[invite["id"]] = invite
        if not self.vapid:
            self.vapid = await self.hass.async_add_executor_job(webpush.generate_keys)
        return invite, token

    def _closed_at(self, invite: dict[str, Any], now: datetime) -> datetime | None:
        """When an invite stopped being usable (used, cancelled or expired); None if open."""
        if self._invite_open(invite, now):
            return None
        closed = _parse(invite.get("closed_at"))
        if closed is not None:
            return closed
        expires = _parse(invite.get("expires_at"))
        if invite.get("status") == OPEN and expires is not None:
            return expires
        return _parse(invite.get("created_at")) or now

    def _in_use(self, invite: dict[str, Any]) -> bool:
        """Used by a phone that is active (or waiting for an adult): its invite stays, so the
        phone keeps the permissions it came with ("Nuovo telefono" copies them)."""
        device = self.devices.get(str(invite.get("device_id") or ""))
        return device is not None and device["status"] in (ACTIVE, PENDING)

    def _cleanup_invites(self) -> bool:
        """Remove invites closed more than 30 days ago. True if something was removed. The
        activity log keeps what happened."""
        now = _now()
        old = [
            invite_id
            for invite_id, invite in self.invites.items()
            if (closed := self._closed_at(invite, now)) is not None
            and now - closed >= INVITE_KEEP
            and not self._in_use(invite)
        ]
        for invite_id in old:
            del self.invites[invite_id]
        return bool(old)

    async def async_delete_invite(self, invite_id: str) -> None:
        """Delete an invite that is no longer usable (used, expired or cancelled)."""
        invite = self.invites.get(invite_id)
        if invite is None:
            raise GuestError("not_found", 404)
        if self._invite_open(invite, _now()):
            raise GuestError("still_open", 409)
        if self._in_use(invite):
            raise GuestError("in_use", 409)
        del self.invites[invite_id]
        await self.async_save()

    async def async_delete_inactive_invites(self) -> int:
        """Delete every invite that is no longer usable. Returns how many."""
        now = _now()
        gone = [
            i
            for i, invite in self.invites.items()
            if not self._invite_open(invite, now) and not self._in_use(invite)
        ]
        for invite_id in gone:
            del self.invites[invite_id]
        if gone:
            await self.async_save()
        return len(gone)

    async def async_revoke_invite(self, invite_id: str) -> None:
        invite = self.invites.get(invite_id)
        if invite is None:
            raise GuestError("not_found", 404)
        if invite["status"] == OPEN:
            invite["status"] = REVOKED
            invite["closed_at"] = _iso(_now())
        self._record("invite_revoked", invite["name"])
        await self.async_save()

    def invite_by_hash(self, digest: str) -> dict[str, Any] | None:
        for invite in self.invites.values():
            if same_hash(invite.get("token_hash"), digest):
                return invite
        return None

    # ----- activation (the phone) ------------------------------------------

    async def async_activate(self, invite: dict[str, Any], user_agent: str) -> str:
        """The phone opened a valid invite: it becomes a device waiting for an adult. The invite
        is used up at once. Returns the device token (shown to that phone only)."""
        if not self._invite_open(invite, _now()):
            await self._refused(invite, user_agent)
            raise GuestError("invite_invalid", 403)
        token = new_token()
        now = _now()
        device = {
            "id": uuid.uuid4().hex,
            "invite_id": invite["id"],
            "name": invite["name"],
            "label": describe_device(user_agent)[:60],
            "activated_at": _iso(now),
            "last_seen": _iso(now),
            "status": PENDING,
            "token_hash": token_hash(token),
            "token_at": _iso(now),
            "prev_hash": None,
            "prev_until": None,
            "persons": list(invite["persons"]),
            "categories": list(invite["categories"]),
            "permission": invite["permission"],
            "approval": invite["approval"],
            "notify": invite["notify"],
            "family_events": bool(invite.get("family_events", False)),
            "has_shifts": bool(invite.get("has_shifts", False)),
            "shift_color": invite.get("shift_color") or DEFAULT_SHIFT_COLOR,
            "shifts_category": invite.get("shifts_category") or "",
            "shifts_person": invite.get("shifts_person") or "",
            **{key: invite[key] for key in gf.KEYS if key in invite},
            # "Nuovo telefono": the guest person (and its shifts) of the old phone.
            "person_id": invite.get("person_id"),
            "push": None,
            "replaces": invite.get("replaces"),
        }
        invite["status"] = USED
        invite["closed_at"] = _iso(now)
        invite["device_id"] = device["id"]
        self.devices[device["id"]] = device
        self._record("activated", device["name"], device["label"])
        await self.async_save()
        self._spawn(self._tell_adults_device(device))
        return token

    async def _refused(self, invite: dict[str, Any], user_agent: str) -> None:
        """Someone opened an invite that is used, expired or cancelled: written in the activity
        log every time, and told to the adults (at most once in ten minutes per invite)."""
        if invite.get("status") == USED:
            kind = "attempt_used"
        elif invite.get("status") == REVOKED:
            kind = "attempt_revoked"
        else:
            kind = "attempt_expired"
        label = describe_device(user_agent)[:60]
        self._record(kind, invite["name"], label)
        await self.async_save()
        now = monotime.monotonic()
        last = self._attempt_told.get(invite["id"])
        if last is not None and now - last < ATTEMPT_NOTICE_SECONDS:
            return
        self._attempt_told[invite["id"]] = now
        message = texts_for(self.language)[kind].format(name=invite["name"], label=label)
        self._spawn(
            self._notify_adults(f"{DOMAIN}_guest_attempt_{invite['id']}", message, message, [])
        )

    def device_by_hash(self, digest: str) -> dict[str, Any] | None:
        now = _now()
        for device in self.devices.values():
            if same_hash(device.get("token_hash"), digest):
                return device
            until = _parse(device.get("prev_until"))
            if until is not None and until > now and same_hash(device.get("prev_hash"), digest):
                return device
        return None

    def touch(self, device: dict[str, Any]) -> None:
        device["last_seen"] = _iso(_now())
        self._save_later()

    async def async_rotate_if_due(self, device: dict[str, Any]) -> str | None:
        """A new device token every 30 days. Returns it, or None when not due."""
        issued = _parse(device.get("token_at"))
        now = _now()
        if issued is not None and now - issued < ROTATE_AFTER:
            return None
        token = new_token()
        device["prev_hash"] = device["token_hash"]
        device["prev_until"] = _iso(now + ROTATE_GRACE)
        device["token_hash"] = token_hash(token)
        device["token_at"] = _iso(now)
        await self._store.async_save(self._data())
        return token

    @staticmethod
    def check_active(device: dict[str, Any]) -> None:
        if device["status"] != ACTIVE:
            raise GuestError(str(device["status"]), 403)

    # ----- devices (adults) -------------------------------------------------

    def _device(self, device_id: str) -> dict[str, Any]:
        device = self.devices.get(device_id)
        if device is None:
            raise GuestError("not_found", 404)
        return device

    async def async_confirm(
        self, device_id: str, accept: bool, from_phone: bool = False
    ) -> dict[str, Any]:
        device = self._device(device_id)
        if device["status"] != PENDING:
            raise GuestError("not_pending", 409)
        device["status"] = ACTIVE if accept else REJECTED
        if not accept:
            device["push"] = None
        self._record("confirmed" if accept else "rejected", device["name"], device["label"])
        self._spawn(self._clear_on_phones(f"{DOMAIN}_guest_{device_id}", from_phone))
        old_id = device.pop("replaces", None)
        if accept and old_id and old_id in self.devices:
            await self._take_place(self.devices[old_id], device)
        await self.async_save()
        if accept:
            # Last: a new or changed guest person reloads Family Hub.
            await self._ensure_person(device)
            await self._update_person(device)
        self._ensure_snapshot()
        return device

    # ----- the guest's own work shifts ------------------------------------------------

    async def _update_options(self, **changes: Any) -> None:
        """Change the entry's options. This reloads Family Hub: the guest store is saved first,
        so the reloaded manager reads everything as it is now."""
        await self._store.async_save(self._data())
        self.hass.config_entries.async_update_entry(
            self.entry, options={**self.entry.options, **changes}
        )

    async def _ensure_person(self, device: dict[str, Any]) -> None:
        """A device with its own shifts has a guest person of the family (its name and colour, no
        Home Assistant account), made once and kept with "Nuovo telefono"."""
        persons = list(self.entry.options.get(OPT_PERSONS, []))
        known = {str(p["id"]) for p in persons}
        if not device.get("has_shifts"):
            return
        target = str(device.get("shifts_person") or "")
        current = device.get("person_id")
        if target and target in known:
            # The shifts are a person of the family's (her models, her calendar): no guest
            # person. What the phone had as a guest person moves onto her.
            device["person_id"] = target
            if current and current != target and self._owns_person(current):
                await self._merge_guest_person(str(current), target, device)
            else:
                await self.async_save()
            return
        if current in known and self._owns_person(current):
            await self._update_person(device, color=device.get("shift_color"))
            return
        person_id = f"guest_{uuid.uuid4().hex[:8]}"
        device["person_id"] = person_id
        persons.append(
            {
                "id": person_id,
                "name": device["name"],
                "color": device.get("shift_color") or DEFAULT_SHIFT_COLOR,
                "role": "guest",
                "channels": [],
                "guest_device": device["id"],
                # Shown in the person filter of Family Hub (guests otherwise are not).
                "has_shifts": True,
            }
        )
        await self._update_options(**{OPT_PERSONS: persons})

    def _owns_person(self, person_id: Any) -> bool:
        """A guest person made for a phone (Family Hub's own, marked by guest_device), as opposed
        to a person of the family the adult linked: that one is never changed or removed here."""
        person = self._persons().get(str(person_id or ""))
        return person is not None and "guest_device" in person

    async def _merge_guest_person(self, old_id: str, new_id: str, device: dict[str, Any]) -> None:
        """The phone's guest person goes into a person of the family: its shift models (by name,
        else added), the shifts it put on days (a day the person already has a shift on keeps hers)
        and its appointments move onto her; then the guest person is removed."""
        options = self.entry.options
        persons = list(options.get(OPT_PERSONS, []))
        all_shifts = dict(options.get(OPT_SHIFTS, {}))
        mine = [dict(m) for m in all_shifts.get(new_id, [])]
        by_name = {str(m["name"]).lower(): m["id"] for m in mine}
        ids = {m["id"] for m in mine}
        mapping: dict[str, str] = {}
        for model in all_shifts.get(old_id, []):
            key = str(model["name"]).lower()
            if key in by_name:
                mapping[model["id"]] = by_name[key]
                continue
            moved = dict(model)
            if moved["id"] in ids:
                moved["id"] = uuid.uuid4().hex[:8]
            mine.append(moved)
            ids.add(moved["id"])
            by_name[key] = moved["id"]
            mapping[model["id"]] = moved["id"]
        all_shifts[new_id] = mine
        all_shifts.pop(old_id, None)
        taken = {
            str(r["start"])[:10]
            for r in self.events.events.values()
            if r.get("shift_id") and new_id in (r.get("persons") or [])
        }
        changed = False
        for uid in list(self.events.events):
            record = self.events.events[uid]
            people = record.get("persons") or []
            if old_id not in people:
                continue
            if record.get("shift_id") and str(record["start"])[:10] in taken:
                self.events.events.pop(uid, None)  # her own shift of that day wins
                changed = True
                continue
            record["persons"] = list(dict.fromkeys(new_id if p == old_id else p for p in people))
            if record.get("shift_id"):
                record["shift_id"] = mapping.get(record["shift_id"], record["shift_id"])
                names = {m["id"]: m["name"] for m in mine}
                record["summary"] = names.get(record["shift_id"], record["summary"])
            changed = True
        for item in self.pending.values():
            event = item["event"]
            event["persons"] = list(
                dict.fromkeys(new_id if p == old_id else p for p in event.get("persons") or [])
            )
        for entry in (*self.devices.values(), *self.invites.values()):
            if old_id in (entry.get("persons") or []):
                entry["persons"] = list(
                    dict.fromkeys(new_id if p == old_id else p for p in entry["persons"])
                )
            if entry.get("person_id") == old_id:
                entry["person_id"] = new_id
        if changed:
            await self.events.async_save()
        persons = [p for p in persons if p["id"] != old_id]
        await self._update_options(**{OPT_PERSONS: persons, OPT_SHIFTS: all_shifts})

    async def _update_person(self, device: dict[str, Any], **fields: Any) -> None:
        person_id = device.get("person_id")
        if not person_id or not self._owns_person(person_id):
            return
        persons = list(self.entry.options.get(OPT_PERSONS, []))
        changed = False
        for index, person in enumerate(persons):
            if person["id"] != person_id:
                continue
            updated = {**person, "guest_device": device["id"]}
            for key, value in fields.items():
                if value:
                    updated[key] = value
            if updated != person:
                persons[index] = updated
                changed = True
        if changed:
            await self._update_options(**{OPT_PERSONS: persons})

    def _shift_person(self, device: dict[str, Any], raw: Any) -> str:
        """The device's own guest person. Asking for anyone else's shifts is refused."""
        self.check_active(device)
        person_id = device.get("person_id")
        if not device.get("has_shifts") or not person_id or person_id not in self._persons():
            raise GuestError("forbidden", 403)
        if isinstance(raw, dict) and raw.get("person") not in (None, person_id):
            raise GuestError("forbidden", 403)
        return str(person_id)

    def _person_name(self, person_id: str, device: dict[str, Any]) -> str:
        return str(self._persons().get(person_id, {}).get("name") or device["name"])

    def shift_types(self, person_id: str) -> list[dict[str, str]]:
        return [dict(t) for t in self.entry.options.get(OPT_SHIFTS, {}).get(person_id, [])]

    def shift_state(self, device: dict[str, Any], start: date, days: int) -> dict[str, Any]:
        person_id = self._shift_person(device, None)
        if not 1 <= days <= MAX_SHIFT_DAYS:
            raise GuestError("invalid", 422)
        zone = dt_util.get_default_time_zone()
        window_start = datetime.combine(start, time(0), tzinfo=zone)
        window_end = window_start + timedelta(days=days)
        names = {t["id"]: t["name"] for t in self.shift_types(person_id)}
        rows = [
            {
                "date": str(record["start"])[:10],
                "shift_id": record.get("shift_id", ""),
                "name": names.get(record.get("shift_id", ""), record["summary"]),
                "start": record["start"],
                "end": record["end"],
            }
            for record in self.events.events.values()
            if record.get("shift_id")
            and person_id in (record.get("persons") or [])
            and _overlaps(record, window_start, window_end)
        ]
        return {
            "types": [
                {"id": t["id"], "name": t["name"], "start": t["start"], "end": t["end"]}
                for t in self.shift_types(person_id)
            ],
            "days": sorted(rows, key=lambda r: r["start"]),
        }

    async def async_save_shift_types(self, device: dict[str, Any], raw: Any) -> None:
        """The guest's shift types (Mattina, Pomeriggio, Notte...). They go to its calendar."""
        person_id = self._shift_person(device, raw)
        items = raw.get("types") if isinstance(raw, dict) else None
        if not isinstance(items, list) or len(items) > 12:
            raise GuestError("invalid", 422)
        category = device.get("shifts_category") or ""
        # A person of the family keeps the calendar each of her models has (the panel's); the
        # guest's own person has the one the invite chose.
        kept: dict[Any, str] = {t["id"]: t["category"] for t in self.shift_types(person_id)}
        linked = bool(device.get("shifts_person"))
        try:
            cleaned = clean_shifts(
                [
                    {
                        **item,
                        "category": kept.get(item.get("id"), category) if linked else category,
                    }
                    for item in items
                    if isinstance(item, dict)
                ],
                set(self._categories()),
            )
        except ShiftError as err:
            raise GuestError("invalid", 422) from err
        if len(cleaned) != len(items):
            raise GuestError("invalid", 422)
        shifts = dict(self.entry.options.get(OPT_SHIFTS, {}))
        shifts[person_id] = cleaned
        # Only the types: nothing changes in the calendar, so the adults are not told.
        await self._update_options(**{OPT_SHIFTS: shifts})

    async def async_apply_shifts(
        self, device: dict[str, Any], raw: Any, *, rotation: bool = False
    ) -> int:
        """Put a shift (or a free day) on chosen days, or a rotation that repeats from a start
        day. Only this guest's own shifts are touched."""
        person_id = self._shift_person(device, raw)
        if not isinstance(raw, dict):
            raise GuestError("invalid", 422)
        types = {t["id"]: t for t in self.shift_types(person_id)}
        today = self._today()
        plan: list[tuple[date, str]] = []
        if rotation:
            pattern = raw.get("pattern")
            count = raw.get("days")
            first = _day(raw.get("start"))
            if (
                not isinstance(pattern, list)
                or not 1 <= len(pattern) <= MAX_ROTATION
                or isinstance(count, bool)
                or not isinstance(count, int)
                or not 1 <= count <= MAX_SHIFT_DAYS
            ):
                raise GuestError("invalid", 422)
            plan = [(first + timedelta(days=i), pattern[i % len(pattern)]) for i in range(count)]
        else:
            days = raw.get("days")
            if not isinstance(days, list) or not 1 <= len(days) <= MAX_SHIFT_DAYS:
                raise GuestError("invalid", 422)
            plan = [(_day(day), raw.get("shift_id") or "") for day in days]
        for day, shift_id in plan:
            if not isinstance(shift_id, str) or (shift_id and shift_id not in types):
                raise GuestError("invalid", 422)
            if not today - timedelta(days=PAST_DAYS) <= day <= today + timedelta(days=FUTURE_DAYS):
                raise GuestError("invalid", 422)
        zone = dt_util.get_default_time_zone()
        written = 0
        self._changing = device["id"]
        try:
            for day, shift_id in plan:
                for record in list(self.events.events.values()):
                    if (
                        record.get("shift_id")
                        and person_id in (record.get("persons") or [])
                        and str(record["start"])[:10] == day.isoformat()
                    ):
                        await self._calendar(record["category"]).async_delete_event(record["uid"])
                if not shift_id:
                    continue  # a free day (riposo)
                shift = types[shift_id]
                start = datetime.combine(day, time.fromisoformat(shift["start"]), tzinfo=zone)
                end_day = day + timedelta(days=1) if shift["end"] < shift["start"] else day
                end = datetime.combine(end_day, time.fromisoformat(shift["end"]), tzinfo=zone)
                await self._calendar(shift["category"]).async_add_event(
                    # "Nonna · Mattina": in Family Hub's calendar, list and notifications.
                    # A person of the family's shifts are written as the panel writes them.
                    summary=(
                        shift["name"]
                        if device.get("shifts_person")
                        else f"{self._person_name(person_id, device)} · {shift['name']}"
                    ),
                    start=start,
                    end=end,
                    persons=[person_id],
                    shift_id=shift_id,
                    added_by={"device": device["id"], "name": device["name"]},
                )
                written += 1
        finally:
            self._changing = None
        self._queue_shift_notice(device, [day for day, _ in plan])
        return written

    def _queue_shift_notice(
        self, device: dict[str, Any], days: list[date], types: bool = False
    ) -> None:
        """The adults hear once, a little later, that the guest changed its shifts."""
        if not self.recipients.get("shifts", True):
            return
        notice = self._shift_notices.setdefault(device["id"], {"days": set(), "types": False})
        notice["days"].update(days)
        notice["types"] = notice["types"] or types
        if device["id"] not in self._shift_timers:
            self._shift_timers[device["id"]] = async_track_point_in_time(
                self.hass, self._shift_flush(device["id"]), _now() + NEW_BATCH
            )

    def _shift_flush(self, device_id: str) -> Callable[[datetime], Any]:
        async def _flush(_moment: datetime) -> None:
            self._shift_timers.pop(device_id, None)
            notice = self._shift_notices.pop(device_id, None)
            device = self.devices.get(device_id)
            if notice is None or device is None:
                return
            text = texts_for(self.language)
            days = sorted(notice["days"])
            today = self._today()
            if days and all(today <= d <= today + timedelta(days=7) for d in days):
                message = text["shifts_week"].format(name=device["name"])
            elif days:
                message = text["shifts_range"].format(
                    name=device["name"],
                    first=days[0].strftime("%d/%m"),
                    last=days[-1].strftime("%d/%m"),
                )
            else:
                message = text["shifts_types"].format(name=device["name"])
            await self._notify_adults(f"{DOMAIN}_guest_shifts_{device_id}", message, message, [])

        return _flush

    async def _drop_person(self, device: dict[str, Any], keep_shifts: bool) -> None:
        """The device goes. Its shifts are the guest's own data: kept (the guest person stays, no
        longer tied to a phone) or deleted with the person, as the adult chose."""
        person_id = device.get("person_id")
        if not person_id or person_id not in self._persons():
            return
        if not self._owns_person(person_id):
            return  # a person of the family: her shifts and herself stay, whatever the phone does
        persons = list(self.entry.options.get(OPT_PERSONS, []))
        if keep_shifts:
            persons = [
                {k: v for k, v in p.items() if k != "guest_device"} if p["id"] == person_id else p
                for p in persons
            ]
            await self._update_options(**{OPT_PERSONS: persons})
            return
        for uid in [
            uid
            for uid, record in self.events.events.items()
            if person_id in (record.get("persons") or []) and record.get("shift_id")
        ]:
            self.events.events.pop(uid, None)
        await self.events.async_save()
        shifts = {k: v for k, v in self.entry.options.get(OPT_SHIFTS, {}).items() if k != person_id}
        persons = [p for p in persons if p["id"] != person_id]
        await self._update_options(**{OPT_PERSONS: persons, OPT_SHIFTS: shifts})

    async def _take_place(self, old: dict[str, Any], new: dict[str, Any]) -> None:
        """The new phone replaces the old one: the appointments "aggiunto da" stay linked to it,
        and the old phone and its used invite go away."""
        changed = False
        for record in self.events.events.values():
            added = record.get("added_by")
            if isinstance(added, dict) and added.get("device") == old["id"]:
                record["added_by"] = {"device": new["id"], "name": new["name"]}
                changed = True
        for item in self.pending.values():
            if item["device_id"] == old["id"]:
                item["device_id"] = new["id"]
        if old.get("person_id") and not new.get("person_id"):
            new["person_id"] = old["person_id"]
        self._forget_device(old["id"])
        self._record("replaced", new["name"], new["label"])
        if changed:
            await self.events.async_save()

    def _forget_device(self, device_id: str) -> None:
        """Remove a device and the invite it used, so nothing is left without its other half."""
        device = self.devices.pop(device_id, None)
        invite_ids = {i for i, inv in self.invites.items() if inv.get("device_id") == device_id}
        if device and device.get("invite_id"):
            invite_ids.add(str(device["invite_id"]))
        for invite_id in invite_ids:
            self.invites.pop(invite_id, None)

    async def async_replace_device(self, device_id: str) -> tuple[dict[str, Any], str]:
        """ "Nuovo telefono": the old phone is turned off at once, and a new invite with the same
        name and permissions is made. Its phone takes the old one's place once confirmed."""
        old = self._device(device_id)
        if old["status"] not in (ACTIVE, DISABLED):
            raise GuestError("not_active", 409)
        if old["status"] == ACTIVE:
            await self.async_disable(device_id)
        scope = {
            key: old.get(key, False if key in ("family_events", "has_shifts") else None)
            for key in (
                "persons",
                "categories",
                "permission",
                "approval",
                "notify",
                "family_events",
                "has_shifts",
                "shift_color",
                "shifts_category",
                "shifts_person",
            )
        }
        scope.update(gf.describe(old))
        invite, token = await self._new_invite(
            old["name"], scope, DEFAULT_EXPIRY_DAYS, replaces=device_id
        )
        invite["person_id"] = old.get("person_id")
        self._record("invite_created", old["name"])
        await self.async_save()
        guest_hub(self.hass).ensure_views()
        return invite, token

    async def async_update_device(self, device_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        device = self._device(device_id)
        rename: str | None = None
        needs_person = False
        if device["status"] in (REJECTED, DISABLED):
            raise GuestError("not_active", 409)
        if "name" in raw:
            name = _text(raw.get("name"), MAX_NAME, required=True)
            if name != device["name"]:
                self._record("renamed", name, device["name"])
                device["name"] = name
                rename = name
        if any(key in raw for key in ("reminder_offsets", "quiet_start", "quiet_end")):
            device.update(self._clean_own_notify(raw, device))
            self._record("permissions", device["name"])
            self._plan_own_reminders()
        if "notify_new" in raw:
            if not isinstance(raw["notify_new"], bool):
                raise GuestError("invalid", 422)
            device["notify_new"] = raw["notify_new"]
        if any(
            key in raw
            for key in (
                "persons",
                "categories",
                "permission",
                "approval",
                "notify",
                "family_events",
                "has_shifts",
                "shift_color",
                "shifts_category",
                "shifts_person",
                *gf.KEYS,
            )
        ):
            scope = self.clean_scope({**device, **raw})
            device.update(scope)
            if not self.push_allowed(device):
                device["push"] = None
            self._record("permissions", device["name"])
            if device["status"] == ACTIVE:
                needs_person = True
        await self.async_save()
        self._ensure_snapshot()
        if needs_person:
            await self._ensure_person(device)
        if rename:
            await self._update_person(device, name=rename)
        return device

    @staticmethod
    def _clean_own_notify(raw: dict[str, Any], device: dict[str, Any]) -> dict[str, Any]:
        """The phone's own reminders: minutes before (None = as the family) and quiet hours
        (both empty = as the family)."""
        offsets = raw.get("reminder_offsets", device.get("reminder_offsets"))
        if offsets is not None and (
            not isinstance(offsets, list)
            or not 1 <= len(offsets) <= MAX_OWN_OFFSETS
            or not all(
                isinstance(o, int) and not isinstance(o, bool) and 0 <= o <= 1440 for o in offsets
            )
        ):
            raise GuestError("invalid_offsets", 422)
        quiet: list[str | None] = []
        for key in ("quiet_start", "quiet_end"):
            value = raw.get(key, device.get(key))
            if value in (None, ""):
                quiet.append(None)
                continue
            _clock(value)
            quiet.append(value)
        if (quiet[0] is None) != (quiet[1] is None):
            raise GuestError("invalid_quiet", 422)
        return {
            "reminder_offsets": None if offsets is None else sorted(set(offsets), reverse=True),
            "quiet_start": quiet[0],
            "quiet_end": quiet[1],
        }

    async def async_disable(self, device_id: str) -> None:
        device = self._device(device_id)
        device["status"] = DISABLED
        device["push"] = None
        # Its waiting appointments go away with it.
        for item_id in [i for i, p in self.pending.items() if p["device_id"] == device_id]:
            del self.pending[item_id]
        self._record("disabled", device["name"], device["label"])
        persistent_notification.async_dismiss(self.hass, f"{DOMAIN}_guest_{device_id}")
        await self.async_save()

    async def async_remove_device(self, device_id: str, keep_shifts: bool | None = None) -> None:
        """Forget a device that is already off (disabled or rejected). A device with its own
        shifts needs the adult's answer: keep them or delete them."""
        device = self._device(device_id)
        if device["status"] not in (DISABLED, REJECTED):
            raise GuestError("still_active", 409)
        has_person = bool(device.get("person_id")) and device["person_id"] in self._persons()
        if has_person and keep_shifts is None:
            raise GuestError("keep_shifts", 409)
        self._forget_device(device_id)
        await self.async_save()
        if has_person:
            await self._drop_person(device, bool(keep_shifts))

    # ----- what a guest sees ------------------------------------------------

    @staticmethod
    def visible(record: dict[str, Any], device: dict[str, Any]) -> bool:
        """An appointment of an allowed calendar with at least one allowed person, or with no
        person at all when the device may see those too. Never a private one."""
        if record.get("private"):
            return False
        persons = record.get("persons") or []
        own = device.get("person_id")
        if own and own in persons and (record.get("shift_id") or not device.get("shifts_person")):
            # Its own shifts and appointments, whatever the calendar. For a person of the family
            # that was linked, only her shifts: the rest follows the calendars chosen.
            return True
        if record.get("category") not in device["categories"]:
            return False
        if not persons:
            return bool(device.get("family_events", False))
        return bool(set(persons) & set(device["persons"]))

    @staticmethod
    def _mine(record: dict[str, Any], device: dict[str, Any]) -> bool:
        added = record.get("added_by") or {}
        return isinstance(added, dict) and added.get("device") == device["id"]

    def guest_event(
        self, record: dict[str, Any], device: dict[str, Any], *, status: str = "ok"
    ) -> dict[str, Any]:
        """Only the fields the web app shows. Persons outside the device's scope are left out,
        with their names and colours."""
        mine = status == "pending" or self._mine(record, device)
        added = record.get("added_by") or {}
        item: dict[str, Any] = {
            "id": record["uid"],
            "title": record["summary"],
            "start": record["start"],
            "end": record["end"],
            "all_day": bool(record["all_day"]),
            "category": record["category"],
            "persons": [
                p
                for p in record.get("persons") or []
                if p in device["persons"] or p == device.get("person_id")
            ],
            "location": record.get("location") or "",
            "added_by": str(added.get("name") or "") if isinstance(added, dict) else "",
            "mine": mine,
            "status": status,
        }
        if mine:
            item["note"] = record.get("description") or ""
            if status == "ok":
                # Sent back with a change: if the appointment is another by then, it is refused.
                item["version"] = event_version(record)
        own = device.get("person_id")
        if record.get("shift_id") and own and own in (record.get("persons") or []):
            item["shift_id"] = str(record["shift_id"])
        if record.get("chosen"):
            item["chosen"] = True
            item["dates"] = self._dates_seen(record, device)
        elif status == "pending" and record.get("dates"):
            item["chosen"] = True
            item["dates"] = [
                {"id": "", "start": d["start"], "end": d["end"], "all_day": d["all_day"]}
                for d in record["dates"]
            ]
        return item

    def _dates_seen(self, record: dict[str, Any], device: dict[str, Any]) -> list[dict[str, Any]]:
        """The dates of a series of chosen dates that this device may see (never a private one)."""
        found = [
            r
            for r in self.events.events.values()
            if r.get("series")
            and r.get("series") == record.get("series")
            and self.visible(r, device)
        ]
        found.sort(key=_start_of)
        return [
            {"id": r["uid"], "start": r["start"], "end": r["end"], "all_day": bool(r["all_day"])}
            for r in found
        ]

    def _affected(
        self, record: dict[str, Any], scope: str, device: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """The dates a change or a delete reaches: ALL every date of the series, THISANDFUTURE
        this one and the later ones. A guest changes only its own: one date that is not its own
        refuses the whole change."""
        items = sorted(
            (
                r
                for r in self.events.events.values()
                if r.get("series") and r.get("series") == record.get("series")
            ),
            key=_start_of,
        )
        if scope == "THISANDFUTURE":
            items = [r for r in items if _start_of(r) >= _start_of(record)]
        if not all(self._mine(r, device) for r in items):
            raise GuestError("forbidden", 403)
        return items

    async def _update_series(
        self, record: dict[str, Any], device: dict[str, Any], scope: str, event: dict[str, Any]
    ) -> None:
        """Change a series of chosen dates from the web app. ALL: the fields of every date, and the
        dates if they are sent (each keeps its own times). THISANDFUTURE: this date and the later
        ones, with the times sent."""
        self._affected(record, scope, device)
        change: dict[str, Any] = {
            "summary": event["summary"],
            "location": event["location"],
            "description": event["description"],
            "persons": event["persons"],
        }
        slots = None
        if scope == "ALL":
            if "dates" in event:
                slots = [_slot_value(item) for item in event["dates"]]
        else:
            change.update(_times(event))
        self._changing = device["id"]
        try:
            await self._calendar(record["category"]).async_update_event(
                record["uid"], change, recurrence_range=scope, dates=slots
            )
        finally:
            self._changing = None

    def me(self, device: dict[str, Any]) -> dict[str, Any]:
        persons = self._persons()
        categories = self._categories()
        result: dict[str, Any] = {"status": device["status"]}
        if device["status"] != ACTIVE:
            return result
        options = self.entry.options
        result.update(
            {
                "name": device["name"],
                "permission": device["permission"],
                "approval": device["approval"],
                "notify": device["notify"],
                "push": device.get("push") is not None,
                "vapid": self.vapid.get("public", "") if self.push_allowed(device) else "",
                **gf.describe(device),
                # The lists it may open: their names, never Home Assistant's entity ids.
                "lists": (lists := self.guest_lists(device) if gf.has(device, gf.LISTS) else []),
                "features": {
                    name: gf.has(device, name) and (name != gf.LISTS or bool(lists))
                    for name in gf.FEATURES
                },
                # The external calendars it may see: name, type and colour, never entity ids.
                "externals": self.guest_externals(device),
                "language": self.language,
                "theme": str(options.get(CONF_THEME) or "auto"),
                "first_weekday": str(options.get(CONF_FIRST_WEEKDAY) or "monday"),
                "time_format": str(options.get(CONF_TIME_FORMAT) or "24h"),
                # As on the wall tablet: the week shown starts today, unless the family chose
                # to start it on the first day of the week.
                "week_from_today": options.get(CONF_WEEK_FROM_TODAY, True) is not False,
                "persons": [
                    {
                        "id": pid,
                        "name": str(persons[pid].get("name", "")),
                        "color": str(persons[pid].get("color") or ""),
                    }
                    for pid in [*device["persons"], device.get("person_id")]
                    if pid and pid in persons
                ],
                "own_person": device.get("person_id") if device.get("person_id") in persons else "",
                # The calendar the guest's own shifts go to (its name, for the shifts board).
                "shifts_calendar": str(
                    categories.get(str(device.get("shifts_category") or ""), {}).get("name", "")
                ),
                "has_shifts": bool(device.get("has_shifts")) and device.get("person_id") in persons,
                "categories": [
                    {
                        "id": cid,
                        "name": str(categories[cid].get("name", "")),
                        "color": str(categories[cid].get("color") or ""),
                    }
                    for cid in device["categories"]
                    if cid in categories
                ],
            }
        )
        return result

    def check_feature(self, device: dict[str, Any], feature: str) -> None:
        """403 for a function the adult did not turn on for this phone."""
        self.check_active(device)
        if not gf.has(device, feature):
            raise GuestError("forbidden", 403)

    def list_events(self, device: dict[str, Any], start: date, days: int) -> list[dict[str, Any]]:
        """The device's appointments that overlap ``days`` days from ``start``, filtered here."""
        self.check_feature(device, gf.CALENDAR)
        if not 1 <= days <= MAX_RANGE_DAYS:
            raise GuestError("invalid", 422)
        zone = dt_util.get_default_time_zone()
        window_start = datetime.combine(start, time(0), tzinfo=zone)
        window_end = window_start + timedelta(days=days)
        items = [
            self.guest_event(record, device)
            for record in self.events.events.values()
            if self.visible(record, device) and _overlaps(record, window_start, window_end)
        ]
        items += [
            self.guest_event({"uid": item_id, **item["event"]}, device, status="pending")
            for item_id, item in self.pending.items()
            if item["device_id"] == device["id"]
            and _overlaps(item["event"], window_start, window_end)
        ]
        return sorted(items, key=lambda item: (_start_of(item), item["title"]))

    # ----- external calendars (0.10.0b2) ---------------------------------------

    def externals(self) -> dict[str, dict[str, Any]]:
        """The external calendars Family Hub shows, by entity id: its own from a file or a link,
        and the Home Assistant calendars chosen in the guide. Rubbish calendars are left out
        (they come with "Giorni dei rifiuti")."""
        found: dict[str, dict[str, Any]] = {}
        manager = getattr(getattr(self.entry, "runtime_data", None), "external", None)
        if manager is not None:
            for source in manager.sources():
                entity = manager.entities.get(source["id"])
                entity_id = getattr(entity, "entity_id", None)
                if not entity_id or source.get("type") == "rifiuti":
                    continue
                found[str(entity_id)] = {
                    "name": str(source.get("name") or ""),
                    "type": str(source.get("type") or "altro"),
                    "color": str(source.get("color") or "#64748B"),
                    "persons": [str(p) for p in source.get("persons") or []],
                    "ics": entity,
                }
        sources = self.entry.options.get("sources") or {}
        styles = sources.get("calendar_styles") or {}
        registry = er.async_get(self.hass)
        for entity_id in sources.get("calendars") or []:
            if not isinstance(entity_id, str) or entity_id in found:
                continue
            registered = registry.async_get(entity_id)
            if registered is not None and registered.platform == DOMAIN:
                continue  # one of Family Hub's own calendars, whatever its name
            style = styles.get(entity_id) or {}
            if style.get("type") == "rifiuti":
                continue
            state = self.hass.states.get(entity_id)
            friendly = state.attributes.get("friendly_name") if state is not None else None
            found[entity_id] = {
                "name": str(
                    style.get("name")
                    or friendly
                    or entity_id.split(".", 1)[-1].replace("_", " ").capitalize()
                ),
                "type": str(style.get("type") or "altro"),
                "color": str(style.get("color") or "#64748B"),
                "persons": [str(p) for p in style.get("persons") or []],
                "ics": None,
            }
        return found

    def _allowed_externals(self, device: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        """The external calendars this phone may see: chosen for it by an adult, still shown by
        Family Hub, and (when the calendar is for some persons) with one of its persons."""
        if not gf.has(device, gf.CALENDAR):
            return []
        known = self.externals()
        visible = {*device["persons"], *([device["person_id"]] if device.get("person_id") else [])}
        return [
            (entity_id, known[entity_id])
            for entity_id in device.get("externals") or []
            if entity_id in known
            and (not known[entity_id]["persons"] or set(known[entity_id]["persons"]) & visible)
        ]

    def guest_externals(self, device: dict[str, Any]) -> list[dict[str, Any]]:
        visible = {*device["persons"], *([device["person_id"]] if device.get("person_id") else [])}
        return [
            {
                "id": gf.external_id(self.entry.entry_id, entity_id),
                "name": info["name"][:60],
                "type": info["type"],
                "color": info["color"],
                "persons": [p for p in info["persons"] if p in visible],
            }
            for entity_id, info in self._allowed_externals(device)
        ]

    async def async_external_events(
        self, device: dict[str, Any], start: date, days: int
    ) -> list[dict[str, Any]]:
        """The events of the external calendars this phone may see, read only. A calendar that
        is not allowed is never read; persons outside the phone's scope are left out."""
        if not 1 <= days <= MAX_RANGE_DAYS:
            raise GuestError("invalid", 422)
        zone = dt_util.get_default_time_zone()
        window_start = datetime.combine(start, time(0), tzinfo=zone)
        window_end = window_start + timedelta(days=days)
        visible = {*device["persons"], *([device["person_id"]] if device.get("person_id") else [])}
        items: list[dict[str, Any]] = []
        for entity_id, info in self._allowed_externals(device):
            if info["ics"] is not None:
                calendar = info["ics"].calendar
                raw = gf.ics_events(calendar, window_start, window_end) if calendar else []
            else:
                raw = await self._ha_events(entity_id, window_start, window_end)
            for event in raw[:MAX_EXTERNAL_EVENTS]:
                first, last = event["start"], event["end"]
                all_day = not isinstance(first, datetime)
                items.append(
                    {
                        # An id of its own (the web app tells events apart by it); it is not
                        # an appointment of Family Hub, so it can never be changed or deleted.
                        "id": "ext"
                        + hashlib.sha256(
                            f"{entity_id}|{first.isoformat()}|{event['summary']}".encode()
                        ).hexdigest()[:16],
                        "title": str(event["summary"])[:MAX_TITLE],
                        "start": first.isoformat()
                        if all_day
                        else dt_util.as_local(first).isoformat(),
                        "end": last.isoformat() if all_day else dt_util.as_local(last).isoformat(),
                        "all_day": all_day,
                        "category": gf.external_id(self.entry.entry_id, entity_id),
                        "external": True,
                        "persons": [p for p in info["persons"] if p in visible],
                        "location": str(event.get("location") or "")[:MAX_LOCATION],
                        "added_by": "",
                        "mine": False,
                        "status": "ok",
                    }
                )
        return items

    async def _ha_events(
        self, entity_id: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        """The events of a Home Assistant calendar in a window; nothing if it cannot be read."""
        try:
            result: Any = await self.hass.services.async_call(
                "calendar",
                "get_events",
                {
                    "entity_id": entity_id,
                    "start_date_time": start.isoformat(),
                    "end_date_time": end.isoformat(),
                },
                blocking=True,
                return_response=True,
            )
        except Exception as err:  # noqa: BLE001 - a calendar that is away must not empty the week
            LOGGER.debug("External calendar %s not readable: %s", entity_id, err)
            return []
        found: list[dict[str, Any]] = []
        for event in (result or {}).get(entity_id, {}).get("events", []):
            try:
                first = _moment(event.get("start"))
                last = _moment(event.get("end"))
            except (TypeError, ValueError):
                continue
            found.append(
                {
                    "summary": str(event.get("summary") or ""),
                    "start": first,
                    "end": last,
                    "location": str(event.get("location") or ""),
                }
            )
        return found

    # ----- lists, rubbish days and weather (0.10) ------------------------------

    def _allowed_lists(self, device: dict[str, Any]) -> list[str]:
        """The lists an adult chose for this phone that are still lists of Family Hub."""
        family = gf.family_lists(self.entry.options)
        return [e for e in device.get("lists") or [] if e in family]

    def guest_lists(self, device: dict[str, Any]) -> list[dict[str, Any]]:
        edit = bool(device.get("lists_edit"))
        entry_id = self.entry.entry_id
        return [
            {"id": gf.list_id(entry_id, e), "name": gf.list_name(self.hass, e), "edit": edit}
            for e in self._allowed_lists(device)
        ]

    def _list_entity(self, device: dict[str, Any], list_id: str, write: bool = False) -> str:
        """The list behind an id of the web app; 403 when it is not one of the phone's lists or
        (for a change) the phone may only read."""
        self.check_feature(device, gf.LISTS)
        if write and not device.get("lists_edit"):
            raise GuestError("forbidden", 403)
        for entity_id in self._allowed_lists(device):
            if hmac.compare_digest(gf.list_id(self.entry.entry_id, entity_id), str(list_id)):
                return entity_id
        raise GuestError("forbidden", 403)

    async def async_list_items(self, device: dict[str, Any], list_id: str) -> list[dict[str, Any]]:
        return await gf.list_items(self.hass, self._list_entity(device, list_id))

    async def async_list_change(self, device: dict[str, Any], list_id: str, raw: Any) -> None:
        """{"add": text} adds an item; {"item": id, "done": bool} ticks or unticks one. Items are
        never deleted from the web app."""
        entity_id = self._list_entity(device, list_id, write=True)
        if not isinstance(raw, dict):
            raise GuestError("invalid", 422)
        try:
            if "add" in raw and set(raw) == {"add"}:
                summary = _text(raw.get("add"), gf.MAX_ITEM, required=True)
                await gf.add_item(self.hass, entity_id, summary)
                self._record("list_added", device["name"], summary)
            elif set(raw) == {"item", "done"} and isinstance(raw.get("done"), bool):
                uid = raw.get("item")
                known = {i["id"] for i in await gf.list_items(self.hass, entity_id)}
                if not isinstance(uid, str) or uid not in known:
                    raise GuestError("not_found", 404)
                await gf.set_done(self.hass, entity_id, uid, raw["done"])
            else:
                raise GuestError("invalid", 422)
        except HomeAssistantError as err:
            raise GuestError("unavailable", 503) from err
        await self.async_save()

    async def async_waste_days(
        self, device: dict[str, Any], start: date, days: int
    ) -> list[dict[str, Any]]:
        """Rubbish pickups: the day and the type (label and colour), nothing else."""
        self.check_feature(device, gf.WASTE)
        if not 1 <= days <= MAX_RANGE_DAYS:
            raise GuestError("invalid", 422)
        external = self.entry.runtime_data.external
        if external is None:
            return []
        visible = [*device["persons"], *([device["person_id"]] if device.get("person_id") else [])]
        return await external.async_waste_days(start, days, visible)

    async def async_weather(self, device: dict[str, Any]) -> dict[str, Any]:
        """Today's weather line of the family's weather entity, or nothing."""
        self.check_feature(device, gf.WEATHER)
        from .weather import summary_line  # noqa: PLC0415

        sources = self.entry.options.get("sources") or {}
        chosen = [e for e in sources.get("weather") or [] if isinstance(e, str)]
        if not chosen:
            return {"line": "", "condition": ""}
        state = self.hass.states.get(chosen[0])
        line = await summary_line(self.hass, chosen[0], self.language)
        attributes = state.attributes if state is not None else {}
        temperature = attributes.get("temperature")
        return {
            "line": line or "",
            "condition": state.state if state is not None else "",
            "temperature": temperature if isinstance(temperature, (int, float)) else None,
            "unit": str(attributes.get("temperature_unit") or "°C")[:4],
            "forecast": await self._forecast(chosen[0]),
        }

    async def _forecast(self, entity_id: str) -> list[dict[str, Any]]:
        """The daily forecast (at most 10 days): only day, condition and temperatures."""
        try:
            result: Any = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": entity_id, "type": "daily"},
                blocking=True,
                return_response=True,
            )
        except Exception as err:  # noqa: BLE001 - the forecast is optional
            LOGGER.debug("No forecast from %s: %s", entity_id, err)
            return []
        days = (result or {}).get(entity_id, {}).get("forecast", [])
        found: list[dict[str, Any]] = []
        for day in days[:10] if isinstance(days, list) else []:
            if not isinstance(day, dict):
                continue
            found.append(
                {
                    "datetime": str(day.get("datetime") or "")[:25],
                    "condition": str(day.get("condition") or "")[:40],
                    **{
                        key: day[key]
                        for key in ("temperature", "templow", "precipitation_probability")
                        if isinstance(day.get(key), (int, float))
                    },
                }
            )
        return found

    # ----- appointments from a guest ---------------------------------------

    def _today(self) -> date:
        return dt_util.as_local(dt_util.now()).date()

    async def async_guest_add(self, device: dict[str, Any], raw: Any) -> dict[str, Any]:
        self.check_feature(device, gf.CALENDAR)
        if device["permission"] not in (ADD, EDIT_OWN):
            raise GuestError("forbidden", 403)
        event = clean_event(raw, device["persons"], device["categories"], self._today())
        added_by = {"device": device["id"], "name": device["name"]}
        if device["approval"] == APPROVE:
            item_id = uuid.uuid4().hex
            self.pending[item_id] = {
                "id": item_id,
                "device_id": device["id"],
                "created_at": _iso(_now()),
                "event": {**event, "added_by": added_by},
            }
            self._record("event_pending", device["name"], event["summary"])
            await self.async_save()
            self._spawn(self._tell_adults_pending(item_id))
            return self.guest_event(
                {"uid": item_id, **self.pending[item_id]["event"]}, device, status="pending"
            )
        uid = await self._write(event, added_by, device["id"])
        self._record("event_added", device["name"], event["summary"])
        await self.async_save()
        return self.guest_event(self.events.events[uid], device)

    async def _write(self, event: dict[str, Any], added_by: dict[str, Any], who: str | None) -> str:
        calendar = self._calendar(event["category"])
        if event.get("dates"):
            slots = [_slot_value(item) for item in event["dates"]]
            self._changing = who
            try:
                return await calendar.async_add_event(
                    summary=event["summary"],
                    start=slots[0][0],
                    end=slots[0][1],
                    description=event.get("description") or None,
                    location=event.get("location") or None,
                    persons=list(event["persons"]),
                    added_by=added_by,
                    dates=slots,
                )
            finally:
                self._changing = None
        all_day = event["all_day"]
        start: date | datetime
        end: date | datetime
        if all_day:
            start, end = date.fromisoformat(event["start"]), date.fromisoformat(event["end"])
        else:
            start, end = (
                datetime.fromisoformat(event["start"]),
                datetime.fromisoformat(event["end"]),
            )
        self._changing = who
        try:
            return await calendar.async_add_event(
                summary=event["summary"],
                start=start,
                end=end,
                description=event.get("description") or None,
                location=event.get("location") or None,
                persons=list(event["persons"]),
                added_by=added_by,
            )
        finally:
            self._changing = None

    def _own(self, device: dict[str, Any], item_id: str) -> tuple[str, dict[str, Any]]:
        """The device's own appointment, stored ("event") or waiting ("pending")."""
        if not isinstance(item_id, str) or not _ID.match(item_id):
            raise GuestError("not_found", 404)
        pending = self.pending.get(item_id)
        if pending is not None and pending["device_id"] == device["id"]:
            return "pending", pending["event"]
        record = self.events.events.get(item_id)
        if record is not None and self._mine(record, device) and self.visible(record, device):
            return "event", record
        raise GuestError("not_found", 404)

    async def async_guest_update(
        self, device: dict[str, Any], item_id: str, raw: Any
    ) -> dict[str, Any]:
        self.check_feature(device, gf.CALENDAR)
        if device["permission"] != EDIT_OWN:
            raise GuestError("forbidden", 403)
        kind, current = self._own(device, item_id)
        version = None
        if isinstance(raw, dict) and "version" in raw:
            version = raw["version"]
            if not isinstance(version, str) or not _VERSION.match(version):
                raise GuestError("invalid", 422)
            raw = {k: v for k, v in raw.items() if k != "version"}
        scope = ""
        if isinstance(raw, dict) and "scope" in raw:
            scope = raw["scope"]
            if scope not in ("", "THISANDFUTURE", "ALL"):
                raise GuestError("invalid", 422)
            raw = {k: v for k, v in raw.items() if k != "scope"}
        event = clean_event(raw, device["persons"], device["categories"], self._today())
        series = kind == "event" and bool(current.get("chosen"))
        if scope and not series:
            raise GuestError("invalid", 422)
        if "dates" in event and (kind == "event" and (scope != "ALL" or not series)):
            raise GuestError("invalid", 422)
        if kind == "event":
            self._check_version(current, version)
        if kind == "pending":
            self.pending[item_id]["event"] = {**event, "added_by": current.get("added_by")}
            self._record("event_changed", device["name"], event["summary"])
            await self.async_save()
            return self.guest_event(
                {"uid": item_id, **self.pending[item_id]["event"]}, device, status="pending"
            )
        added_by = dict(current.get("added_by") or {})
        if scope:
            if event["category"] != current["category"]:
                raise GuestError("invalid", 422)
            uid = item_id
            await self._update_series(current, device, scope, event)
        elif event["category"] != current["category"]:
            # Another calendar: the appointment moves there with a new id.
            await self._delete_record(current, device["id"])
            uid = await self._write(event, added_by, device["id"])
        else:
            uid = item_id
            calendar = self._calendar(current["category"])
            change: dict[str, Any] = {
                "summary": event["summary"],
                "location": event["location"],
                "description": event["description"],
                "persons": event["persons"],
            }
            if event["all_day"]:
                change["dtstart"] = date.fromisoformat(event["start"])
                change["dtend"] = date.fromisoformat(event["end"])
            else:
                change["dtstart"] = datetime.fromisoformat(event["start"])
                change["dtend"] = datetime.fromisoformat(event["end"])
            self._changing = device["id"]
            try:
                await calendar.async_update_event(uid, change, version=version)
            finally:
                self._changing = None
        self._record("event_changed", device["name"], event["summary"])
        await self.async_save()
        return self.guest_event(self.events.events[uid], device)

    async def _delete_record(self, record: dict[str, Any], who: str | None) -> None:
        calendar = self._calendar(record["category"])
        self._changing = who
        try:
            await calendar.async_delete_event(record["uid"])
        finally:
            self._changing = None

    @staticmethod
    def _check_version(record: dict[str, Any], version: str | None) -> None:
        """The change was made on the version the phone read: 409 when it is another now."""
        if version and event_version(record) != version:
            raise GuestError("event_changed", 409)

    async def async_guest_delete(
        self,
        device: dict[str, Any],
        item_id: str,
        version: str | None = None,
        scope: str = "",
    ) -> None:
        self.check_feature(device, gf.CALENDAR)
        if device["permission"] != EDIT_OWN:
            raise GuestError("forbidden", 403)
        if version is not None and not _VERSION.match(version):
            raise GuestError("invalid", 422)
        if scope not in ("", "THISANDFUTURE", "ALL"):
            raise GuestError("invalid", 422)
        kind, current = self._own(device, item_id)
        if kind == "event":
            self._check_version(current, version)
        if kind == "pending":
            if scope:
                raise GuestError("invalid", 422)
            del self.pending[item_id]
        elif scope:
            if not current.get("chosen"):
                raise GuestError("invalid", 422)
            self._affected(current, scope, device)
            self._changing = device["id"]
            try:
                await self._calendar(current["category"]).async_delete_event(
                    current["uid"], recurrence_range=scope
                )
            finally:
                self._changing = None
        else:
            await self._delete_record(current, device["id"])
        self._record("event_deleted", device["name"], str(current.get("summary", "")))
        await self.async_save()

    # ----- approval (adults) ------------------------------------------------

    async def async_approve(
        self,
        item_id: str,
        accept: bool,
        changes: dict[str, Any] | None = None,
        from_phone: bool = False,
    ) -> str | None:
        """Approve (optionally with an adult's changes) or reject a waiting appointment."""
        item = self.pending.get(item_id)
        if item is None:
            raise GuestError("not_found", 404)
        device = self.devices.get(item["device_id"])
        event = dict(item["event"])
        name = device["name"] if device else str((event.get("added_by") or {}).get("name", ""))
        uid: str | None = None
        if accept:
            if changes:
                # An adult may put it in any person and calendar of the family.
                cleaned = clean_event(
                    changes,
                    list(self._persons()),
                    list(self._categories()),
                    self._today(),
                    any_date=True,
                )
                # A series of chosen dates keeps its dates: the adult changes all of them.
                if event.get("dates") and "dates" not in cleaned:
                    cleaned = {**cleaned, "dates": event["dates"]}
                event = {**cleaned, "added_by": event.get("added_by")}
            uid = await self._write(event, dict(event.get("added_by") or {}), None)
        del self.pending[item_id]
        self._record("approved" if accept else "declined", name, str(event["summary"]))
        self._spawn(self._clear_on_phones(f"{DOMAIN}_guest_{item_id}", from_phone))
        await self.async_save()
        if device is not None and device["status"] == ACTIVE and device.get("notify"):
            text = texts_for(self.language)
            key = "approved" if accept else "declined"
            message = text[key].format(title=event["summary"], when=self._when(event))
            self._spawn(
                self._push(device, {"title": text["title"], "body": message, "tag": item_id})
            )
        return uid

    # ----- describing appointments -----------------------------------------

    def _when(self, record: dict[str, Any]) -> str:
        text = texts_for(self.language)
        if record.get("all_day"):
            day = date.fromisoformat(str(record["start"])[:10])
            return f"{day.strftime('%d/%m')} · {text['all_day']}"
        start = dt_util.as_local(datetime.fromisoformat(str(record["start"])))
        clock = "%I:%M %p" if self.entry.options.get(CONF_TIME_FORMAT) == "12h" else "%H:%M"
        return f"{start.strftime('%d/%m')} {start.strftime(clock)}"

    # ----- notifications to adults -----------------------------------------

    async def async_set_recipients(self, raw: Any) -> None:
        if not isinstance(raw, dict) or raw.get("mode") not in RECIPIENT_MODES:
            raise GuestError("invalid", 422)
        persons = raw.get("persons", [])
        known = self._persons()
        if not isinstance(persons, list) or not all(
            isinstance(p, str) and p in known for p in persons
        ):
            raise GuestError("invalid_persons", 422)
        if raw["mode"] == RECIPIENTS_PERSONS and not persons:
            raise GuestError("invalid_persons", 422)
        shifts = raw.get("shifts", True)
        if not isinstance(shifts, bool):
            raise GuestError("invalid", 422)
        self.recipients = {
            "mode": raw["mode"],
            "persons": list(dict.fromkeys(persons)),
            "shifts": shifts,
        }
        await self.async_save()

    async def async_set_panel(self, path: Any) -> None:
        """The add-on says where Family Hub opens (/app/<slug>): a tapped notification goes
        there."""
        if not isinstance(path, str) or not re.fullmatch(r"/[A-Za-z0-9_/-]{1,80}", path):
            raise GuestError("invalid", 422)
        if path != self.panel:
            self.panel = path
            await self._store.async_save(self._data())

    def _person_phones(self) -> list[str]:
        """The phones of the adults, or of the persons chosen in "Chi riceve le richieste"."""
        persons = self._persons()
        if self.recipients.get("mode") == RECIPIENTS_PERSONS:
            chosen = [persons[p] for p in self.recipients.get("persons", []) if p in persons]
        else:
            chosen = [p for p in persons.values() if p.get("role", "adult") == "adult"]
        phones = [str(p["phone_notify"]) for p in chosen if p.get("phone_notify")]
        return [p for p in dict.fromkeys(phones) if self.hass.services.has_service("notify", p)]

    async def _admin_phones(self) -> list[str]:
        """The Companion app phones of Home Assistant's administrators: each phone's own user,
        as the mobile app integration records it, and its notify service as that integration
        names it."""
        phones: list[str] = []
        for entry in self.hass.config_entries.async_entries("mobile_app"):
            user_id = entry.data.get("user_id")
            device_name = entry.data.get("device_name")
            if not user_id or not device_name:
                continue
            user = await self.hass.auth.async_get_user(str(user_id))
            if user is None or not user.is_active or not user.is_admin:
                continue
            service = slugify(f"mobile_app_{device_name}")
            if self.hass.services.has_service("notify", service):
                phones.append(service)
        return list(dict.fromkeys(phones))

    async def recipient_phones(self) -> list[str]:
        return self._person_phones() or await self._admin_phones()

    async def _notify_adults(
        self,
        notification_id: str,
        phone_message: str,
        tablet_message: str,
        actions: list[dict[str, str]],
        open_what: str = "",
    ) -> None:
        text = texts_for(self.language)
        persistent_notification.async_create(
            self.hass, tablet_message, title=text["title"], notification_id=notification_id
        )
        data: dict[str, Any] = {"tag": notification_id}
        if actions:
            data["actions"] = actions
        if self.panel:
            # Tapping the notification opens Family Hub on what it is about.
            url = self.open_url(open_what) if open_what else self.panel
            data["url"] = url
            data["clickAction"] = url
        for phone in await self.recipient_phones():
            try:
                await self.hass.services.async_call(
                    "notify",
                    phone,
                    {"title": text["title"], "message": phone_message, "data": dict(data)},
                    blocking=True,
                )
            except HomeAssistantError:
                LOGGER.warning("Family Hub could not reach an adult's phone")

    def open_url(self, what: str) -> str:
        """The address a tapped notification opens: Family Hub's page in Home Assistant, with
        what to show (fh_open=device.<id> / pending.<id> / event.<uid>.<date>)."""
        return f"{self.panel}?fh_open={what}" if self.panel else ""

    async def _clear_on_phones(self, notification_id: str, from_phone: bool = False) -> None:
        """Answered on one phone (or on the tablet): the same request goes from the others."""
        persistent_notification.async_dismiss(self.hass, notification_id)
        phones = await self.recipient_phones()
        if from_phone and len(phones) < 2:
            return  # answered on the only phone: nothing to take away elsewhere
        for phone in phones:
            try:
                await self.hass.services.async_call(
                    "notify",
                    phone,
                    {"message": "clear_notification", "data": {"tag": notification_id}},
                    blocking=True,
                )
            except HomeAssistantError:
                LOGGER.warning("Family Hub could not reach an adult's phone")

    async def _tell_adults_device(self, device: dict[str, Any]) -> None:
        text = texts_for(self.language)
        values = {"label": device["label"], "name": device["name"]}
        await self._notify_adults(
            f"{DOMAIN}_guest_{device['id']}",
            text["device_waiting"].format(**values),
            text["device_waiting_tablet"].format(**values),
            [
                {"action": f"{ACTION_PREFIX}CONFIRM_{device['id']}", "title": text["confirm"]},
                {"action": f"{ACTION_PREFIX}REJECT_{device['id']}", "title": text["reject"]},
            ],
            open_what=f"device.{device['id']}",
        )

    async def _tell_adults_pending(self, item_id: str) -> None:
        item = self.pending.get(item_id)
        if item is None:
            return
        device = self.devices.get(item["device_id"]) or {}
        text = texts_for(self.language)
        values = {
            "name": device.get("name", ""),
            "title": item["event"]["summary"],
            "when": self._when(item["event"]),
        }
        await self._notify_adults(
            f"{DOMAIN}_guest_{item_id}",
            text["to_approve"].format(**values),
            text["to_approve_tablet"].format(**values),
            [
                {"action": f"{ACTION_PREFIX}APPROVE_{item_id}", "title": text["approve"]},
                {"action": f"{ACTION_PREFIX}DECLINE_{item_id}", "title": text["decline"]},
            ],
            open_what=f"pending.{item_id}",
        )

    async def async_handle_action(self, action: str) -> bool:
        """A button on an adult's phone: FH_GUEST_<CONFIRM|REJECT|APPROVE|DECLINE>_<id>.
        True when the action was one of this family's."""
        command, _, item_id = action.removeprefix(ACTION_PREFIX).partition("_")
        try:
            if command in ("CONFIRM", "REJECT") and item_id in self.devices:
                await self.async_confirm(item_id, command == "CONFIRM", from_phone=True)
                return True
            if command in ("APPROVE", "DECLINE") and item_id in self.pending:
                await self.async_approve(item_id, command == "APPROVE", from_phone=True)
                return True
        except GuestError:
            return True
        return False

    # ----- push to guests -----------------------------------------------------

    def _spawn(self, coro: Any) -> None:
        task = self.hass.async_create_background_task(coro, f"{DOMAIN} guest")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _subject(self) -> str:
        """The contact in the VAPID claims: the family's own Home Assistant address."""
        from homeassistant.helpers.network import NoURLAvailableError, get_url  # noqa: PLC0415

        try:
            url = get_url(self.hass, allow_internal=False, require_ssl=True)
        except NoURLAvailableError:
            return "mailto:family-hub@localhost.localdomain"
        return url

    async def _push(self, device: dict[str, Any], payload: dict[str, Any]) -> None:
        subscription = device.get("push")
        if not subscription or not self.push_allowed(device) or not self.vapid:
            return
        result = await webpush.async_send(
            self.hass, subscription, payload, self.vapid["private"], self._subject()
        )
        if result == webpush.GONE:
            device["push"] = None
            await self._store.async_save(self._data())

    async def async_set_blocked(self, device: dict[str, Any], blocked: bool) -> None:
        """The phone says its notifications are blocked in its settings (or no longer)."""
        self.check_active(device)
        if bool(device.get("push_blocked")) != blocked:
            device["push_blocked"] = blocked
            if blocked:
                device["push"] = None
            await self.async_save()

    @staticmethod
    def push_status(device: dict[str, Any]) -> str:
        if device.get("push"):
            return PUSH_ACTIVE
        return PUSH_BLOCKED if device.get("push_blocked") else PUSH_OFF

    async def async_test_push(self, device_id: str) -> None:
        """ "Invia notifica di prova": at most one a minute per phone."""
        device = self._device(device_id)
        self.check_active(device)
        if not device.get("push") or not self.push_allowed(device):
            raise GuestError("no_push", 409)
        now = monotime.monotonic()
        last = self._test_sent.get(device_id)
        if last is not None and now - last < TEST_PUSH_EVERY:
            raise GuestError("slow_down", 429)
        self._test_sent[device_id] = now
        text = texts_for(self.language)
        await self._push(device, {"title": text["title"], "body": text["test_push"], "tag": "test"})

    async def async_set_push(self, device: dict[str, Any], raw: Any) -> bool:
        self.check_active(device)
        if raw is None:
            device["push"] = None
        else:
            if not self.push_allowed(device):
                raise GuestError("forbidden", 403)
            subscription = webpush.clean_subscription(raw)
            if subscription is None:
                raise GuestError("invalid", 422)
            device["push"] = subscription
            device["push_blocked"] = False
        await self.async_save()
        self._plan_own_reminders()
        self._ensure_snapshot()
        return device["push"] is not None

    def _ensure_snapshot(self) -> None:
        """Remember the appointments as they are, once a guest listens: the next save tells
        what is new or changed against this."""
        if self._snapshot is None and self._listeners():
            records = self.events.events
            self._snapshot = {uid: self._shape(r) for uid, r in records.items()}
            self._snapshot_records = {uid: dict(r) for uid, r in records.items()}

    @staticmethod
    def push_allowed(device: dict[str, Any]) -> bool:
        """Notifications (changes, new appointments, answers) or reminders: either needs push."""
        return bool(device.get("notify")) or gf.has(device, gf.REMINDERS)

    def _listeners(self, kind: str = "") -> list[dict[str, Any]]:
        """Phones that receive pushes; with ``kind`` "notify" or "reminders", only those that
        have that function on."""
        return [
            d
            for d in self.devices.values()
            if d["status"] == ACTIVE
            and d.get("push")
            and self.push_allowed(d)
            and (kind != "notify" or bool(d.get("notify")))
            and (kind != "reminders" or gf.has(d, gf.REMINDERS))
        ]

    def _quiet_for(self, device: dict[str, Any]) -> bool:
        """The phone's own quiet hours when set, else the family's."""
        if device.get("quiet_start") and device.get("quiet_end"):
            from .reminders import in_quiet_hours  # noqa: PLC0415

            now = dt_util.as_local(dt_util.now()).time()
            return in_quiet_hours(now, _clock(device["quiet_start"]), _clock(device["quiet_end"]))
        return self._quiet_now()

    def _plan_own_reminders(self) -> None:
        """Timers for the phones with their own minutes before (timed appointments they see),
        for the next two days; planned again every hour and after every change."""
        for cancel in self._own_timers.values():
            cancel()
        self._own_timers.clear()
        now = _now()
        until = now + OWN_REMINDERS_AHEAD
        devices = [d for d in self._listeners("reminders") if d.get("reminder_offsets") is not None]
        for device in devices:
            for record in self.events.events.values():
                if record.get("all_day") or record.get("reminders_off"):
                    continue
                if not self.visible(record, device):
                    continue
                start = _start_of(record)
                for offset in device["reminder_offsets"]:
                    moment = start - timedelta(minutes=int(offset))
                    key = (device["id"], record["uid"], moment.isoformat())
                    if not now < moment <= until or key in self._own_sent:
                        continue
                    self._own_timers[key] = async_track_point_in_time(
                        self.hass, self._own_reminder(key), moment
                    )

    def _own_reminder(self, key: tuple[str, str, str]) -> Callable[[datetime], Any]:
        async def _fire(_now: datetime) -> None:
            self._own_timers.pop(key, None)
            device = self.devices.get(key[0])
            record = self.events.events.get(key[1])
            if device is None or record is None or key in self._own_sent:
                return
            if device not in self._listeners("reminders") or not self.visible(record, device):
                return
            self._own_sent.add(key)
            if self._quiet_for(device):
                return
            text = texts_for(self.language)
            clock = "%I:%M %p" if self.entry.options.get(CONF_TIME_FORMAT) == "12h" else "%H:%M"
            when = dt_util.as_local(_start_of(record)).strftime(clock)
            payload = {
                "title": text["reminder"],
                "body": f"{when} · {record['summary']}",
                "tag": record["uid"],
            }
            await self._push(device, payload)

        return _fire

    def _quiet_now(self) -> bool:
        from .reminders import _clock, in_quiet_hours  # noqa: PLC0415

        settings = {**DEFAULT_REMINDERS, **self.entry.options.get(OPT_REMINDERS, {})}
        now = dt_util.as_local(dt_util.now()).time()
        return in_quiet_hours(now, _clock(settings["quiet_start"]), _clock(settings["quiet_end"]))

    async def async_on_reminder(self, record: dict[str, Any], message: str) -> None:
        """A family reminder went out: guests who see the appointment get it too, at the same
        moment, outside the family's quiet hours."""
        listeners = [
            d
            for d in self._listeners("reminders")
            if self.visible(record, d)
            and not self._quiet_for(d)
            # Timed appointments of a phone with its own minutes are planned for it apart.
            and (d.get("reminder_offsets") is None or bool(record.get("all_day")))
        ]
        if not listeners:
            return
        now = monotime.monotonic()
        self._reminded = {k: t for k, t in self._reminded.items() if t > now - 120}
        key = f"{record['uid']}|{message}"
        if key in self._reminded:
            return  # the same reminder for several persons of one appointment
        self._reminded[key] = now
        text = texts_for(self.language)
        payload = {"title": text["reminder"], "body": message, "tag": record["uid"]}
        for device in listeners:
            self._spawn(self._push(device, payload))

    @staticmethod
    def _shape(record: dict[str, Any]) -> tuple[Any, ...]:
        return (
            record.get("summary"),
            record.get("start"),
            record.get("end"),
            record.get("category"),
            tuple(record.get("persons") or []),
            record.get("location"),
            bool(record.get("private")),
        )

    async def async_store_changed(self) -> None:
        """After every save of the appointments: guests hear about changes and cancellations of
        appointments they can see (not about their own changes, nor past appointments)."""
        self._plan_own_reminders()
        if not self._listeners():
            self._snapshot = None
            return
        records = self.events.events
        current = {uid: self._shape(r) for uid, r in records.items()}
        old, old_records = self._snapshot, self._snapshot_records
        self._snapshot = current
        self._snapshot_records = {uid: dict(r) for uid, r in records.items()}
        if old is None:
            return
        now = _now()
        changed = [uid for uid in old if uid in current and current[uid] != old[uid]]
        gone = [uid for uid in old if uid not in current]
        added = [uid for uid in current if uid not in old]
        text = texts_for(self.language)
        for device in self._listeners("notify"):
            if device["id"] == self._changing:
                continue
            # New for this guest: a new appointment it can see, or one it can see from now on
            # (a person or a calendar added). Not its own ones, not past ones.
            news = [
                uid
                for uid in added
                if self.visible(records[uid], device)
                and not self._mine(records[uid], device)
                and _start_of(records[uid]) > now
            ] + [
                uid
                for uid in changed
                if not self.visible(old_records[uid], device)
                and self.visible(records[uid], device)
                and not self._mine(records[uid], device)
                and _start_of(records[uid]) > now
            ]
            if news and device.get("notify_new", True) is not False:
                self._queue_new(device["id"], news)
            changed_here = [uid for uid in changed if uid not in news]
            messages: list[str] = []
            for uid in gone:
                before = old_records[uid]
                if self.visible(before, device) and _start_of(before) > now:
                    title = before["summary"]
                    messages.append(text["cancelled"].format(title=title, when=self._when(before)))
            for uid in changed_here:
                before, after = old_records[uid], records[uid]
                if not self.visible(before, device) and not self.visible(after, device):
                    continue
                if max(_start_of(before), _start_of(after)) <= now:
                    continue
                if self.visible(after, device):
                    title = after["summary"]
                    messages.append(text["changed"].format(title=title, when=self._when(after)))
                else:
                    title = before["summary"]
                    messages.append(text["cancelled"].format(title=title, when=self._when(before)))
            if len(messages) > MAX_CHANGE_PUSHES:
                messages = [text["many_changes"]]
            for message in messages:
                self._spawn(self._push(device, {"title": text["title"], "body": message}))

    def _queue_new(self, device_id: str, uids: list[str]) -> None:
        """Collect new appointments for a while; one message tells them (or sums them up)."""
        queue = self._new_queue.setdefault(device_id, [])
        queue.extend(uid for uid in uids if uid not in queue)
        if device_id not in self._new_timers:
            self._new_timers[device_id] = async_track_point_in_time(
                self.hass, self._new_flush(device_id), _now() + NEW_BATCH
            )

    def _quiet_end(self, device: dict[str, Any]) -> datetime:
        """When the quiet hours that apply to the device end next (local time)."""
        settings = {**DEFAULT_REMINDERS, **self.entry.options.get(OPT_REMINDERS, {})}
        end_text = (
            device["quiet_end"]
            if device.get("quiet_start") and device.get("quiet_end")
            else settings["quiet_end"]
        )
        end = _clock(end_text)
        now = dt_util.as_local(dt_util.now())
        moment = now.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
        if moment <= now:
            moment += timedelta(days=1)
        return dt_util.as_utc(moment)

    def _new_flush(self, device_id: str) -> Callable[[datetime], Any]:
        async def _flush(_moment: datetime) -> None:
            self._new_timers.pop(device_id, None)
            device = self.devices.get(device_id)
            if device is None or device not in self._listeners("notify"):
                self._new_queue.pop(device_id, None)
                return
            if self._quiet_for(device):
                # Told when the quiet hours end.
                self._new_timers[device_id] = async_track_point_in_time(
                    self.hass, self._new_flush(device_id), self._quiet_end(device)
                )
                return
            now = _now()
            records = [
                self.events.events[uid]
                for uid in self._new_queue.pop(device_id, [])
                if uid in self.events.events
                and self.visible(self.events.events[uid], device)
                and _start_of(self.events.events[uid]) > now
            ]
            if records:
                await self._push(device, self._new_payload(device, records))

        return _flush

    def _when_long(self, record: dict[str, Any]) -> str:
        """ "lun 16/11 ore 07:00", "Mon 16/11 at 07:00"; for a whole day only the day."""
        text = texts_for(self.language)
        days = text["days"].split()
        start = dt_util.as_local(_start_of(record))
        day = f"{days[start.weekday()]} {start.strftime('%d/%m')}"
        if record.get("all_day"):
            return day
        clock = "%I:%M %p" if self.entry.options.get(CONF_TIME_FORMAT) == "12h" else "%H:%M"
        return f"{day} {text['at']} {start.strftime(clock)}"

    def _new_payload(self, device: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
        text = texts_for(self.language)
        persons = self._persons()
        names = list(
            dict.fromkeys(
                str(persons[p].get("name", ""))
                for record in records
                for p in record.get("persons") or []
                if p in device["persons"] and p in persons
            )
        )
        who = text["and"].join(names)
        records = sorted(records, key=_start_of)
        first = records[0]
        if len(records) == 1:
            key = "new_one" if who else "new_one_family"
            body = text[key].format(who=who, title=first["summary"], when=self._when_long(first))
        else:
            key = "new_many" if who else "new_many_family"
            body = text[key].format(n=len(records), who=who)
        day = dt_util.as_local(_start_of(first)).date().isoformat()
        return {
            "title": text["title"],
            "body": body,
            "tag": f"new-{first['uid']}",
            # A tap opens the web app on this appointment (the first one of a summary).
            "open": first["uid"],
            "day": day,
        }

    # ----- adults' view --------------------------------------------------

    def describe(self) -> dict[str, Any]:
        """Everything the "Condivisione" page shows. Never a token, hash, key or subscription."""
        now = _now()
        invites = []
        for invite in self.invites.values():
            status = invite["status"]
            if status == OPEN and not self._invite_open(invite, now):
                status = EXPIRED
            invites.append(
                {
                    key: invite.get(key)
                    for key in (
                        "id",
                        "name",
                        "persons",
                        "categories",
                        "permission",
                        "approval",
                        "notify",
                        "created_at",
                        "expires_at",
                        "device_id",
                        "replaces",
                    )
                }
                | {
                    "family_events": bool(invite.get("family_events", False)),
                    "has_shifts": bool(invite.get("has_shifts", False)),
                    "shift_color": invite.get("shift_color") or DEFAULT_SHIFT_COLOR,
                    "shifts_category": invite.get("shifts_category") or "",
                    "shifts_person": invite.get("shifts_person") or "",
                }
                | gf.describe(invite)
                | {"status": status, "in_use": self._in_use(invite)}
            )
        devices = [
            {
                key: device.get(key)
                for key in (
                    "id",
                    "name",
                    "label",
                    "activated_at",
                    "last_seen",
                    "status",
                    "persons",
                    "categories",
                    "permission",
                    "approval",
                    "notify",
                )
            }
            | {
                "push": device.get("push") is not None,
                "push_status": self.push_status(device),
                "reminder_offsets": device.get("reminder_offsets"),
                "family_events": bool(device.get("family_events", False)),
                "notify_new": device.get("notify_new", True) is not False,
                "has_shifts": bool(device.get("has_shifts", False)),
                "shift_color": device.get("shift_color") or DEFAULT_SHIFT_COLOR,
                "shifts_category": device.get("shifts_category") or "",
                "shifts_person": device.get("shifts_person") or "",
                "person_id": device.get("person_id") or "",
                "quiet_start": device.get("quiet_start"),
                "quiet_end": device.get("quiet_end"),
            }
            | gf.describe(device)
            for device in self.devices.values()
        ]
        pending = []
        for item in self.pending.values():
            device = self.devices.get(item["device_id"]) or {}
            event = item["event"]
            pending.append(
                {
                    "id": item["id"],
                    "device": device.get("name", ""),
                    "created_at": item["created_at"],
                    "title": event["summary"],
                    "start": event["start"],
                    "end": event["end"],
                    "all_day": event["all_day"],
                    "category": event["category"],
                    "persons": event["persons"],
                    "location": event.get("location", ""),
                    "note": event.get("description", ""),
                    # A series of chosen dates: the adult confirms all of them, and sees each one.
                    "dates": list(event.get("dates") or []),
                }
            )
        if any(d["status"] == PENDING for d in self.devices.values()):
            attention = "devices"
        elif self.pending:
            attention = "approvals"
        else:
            attention = ""
        return {
            # What waits for an adult: the page opens it by itself (a tapped notification).
            "attention": attention,
            "recipients": dict(self.recipients),
            "invites": sorted(invites, key=lambda i: str(i["created_at"]), reverse=True),
            "devices": sorted(devices, key=lambda d: str(d["activated_at"]), reverse=True),
            "pending": sorted(pending, key=lambda p: str(p["created_at"])),
            "log": list(reversed(self.log)),
        }

    def diagnostics(self) -> dict[str, Any]:
        """Counts only; tokens, keys and subscriptions are left out."""
        return {
            "invites": {
                s: sum(1 for i in self.invites.values() if i["status"] == s)
                for s in (OPEN, USED, REVOKED)
            },
            "devices": {
                s: sum(1 for d in self.devices.values() if d["status"] == s)
                for s in (PENDING, ACTIVE, REJECTED, DISABLED)
            },
            "push_subscriptions": sum(1 for d in self.devices.values() if d.get("push")),
            "pending": len(self.pending),
            "log_entries": len(self.log),
            "vapid": "**REDACTED**" if self.vapid else None,
        }

    @callback
    def async_stop(self) -> None:
        if self._unsub_cleanup is not None:
            self._unsub_cleanup()
            self._unsub_cleanup = None
        if self._unsub_own is not None:
            self._unsub_own()
            self._unsub_own = None
        for cancel in list(self._new_timers.values()) + list(self._shift_timers.values()):
            cancel()
        self._new_timers.clear()
        self._shift_timers.clear()
        for cancel in self._own_timers.values():
            cancel()
        self._own_timers.clear()
        for task in list(self._tasks):
            task.cancel()


def _start_of(record: dict[str, Any]) -> datetime:
    value = str(record["start"])
    if bool(record.get("all_day")) or len(value) == 10:
        return datetime.combine(
            date.fromisoformat(value[:10]), time(0), tzinfo=dt_util.get_default_time_zone()
        )
    return dt_util.as_utc(datetime.fromisoformat(value))


def _end_of(record: dict[str, Any]) -> datetime:
    value = str(record["end"])
    if bool(record.get("all_day")) or len(value) == 10:
        return datetime.combine(
            date.fromisoformat(value[:10]), time(0), tzinfo=dt_util.get_default_time_zone()
        )
    return dt_util.as_utc(datetime.fromisoformat(value))


def _overlaps(record: dict[str, Any], start: datetime, end: datetime) -> bool:
    return _start_of(record) < end and _end_of(record) > start
