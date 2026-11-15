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
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import webpush
from .const import (
    CONF_FIRST_WEEKDAY,
    CONF_LANGUAGE,
    CONF_TIME_FORMAT,
    DEFAULT_REMINDERS,
    DOMAIN,
    OPT_CATEGORIES,
    OPT_PERSONS,
    OPT_REMINDERS,
)

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
        "reminder": "Promemoria",
        "all_day": "tutto il giorno",
        "tomorrow": "domani",
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
        "reminder": "Erinnerung",
        "all_day": "ganztägig",
        "tomorrow": "morgen",
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
        "reminder": "Reminder",
        "all_day": "all day",
        "tomorrow": "tomorrow",
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


EVENT_KEYS = {"title", "person", "category", "date", "all_day", "start", "end", "location", "note"}


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
    local zone: summary, category, persons, start, end, all_day, location, description.
    """
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
        raise GuestError("invalid", 422)
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
        if self.in_use():
            guest_hub(self.hass).ensure_views()

    def _data(self) -> dict[str, Any]:
        return {
            "invites": self.invites,
            "devices": self.devices,
            "pending": self.pending,
            "log": self.log,
            "vapid": self.vapid,
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
        permission = raw.get("permission", VIEW)
        approval = raw.get("approval", APPROVE)
        notify = raw.get("notify", True)
        if permission not in PERMISSIONS or approval not in APPROVALS:
            raise GuestError("invalid", 422)
        if not isinstance(notify, bool):
            raise GuestError("invalid", 422)
        return {
            "persons": list(dict.fromkeys(persons)),
            "categories": list(dict.fromkeys(categories)),
            "permission": permission,
            "approval": approval,
            "notify": notify,
        }

    async def async_create_invite(self, raw: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """A new invite. Returns it and its token: the token is shown once and never kept."""
        name = _text(raw.get("name"), MAX_NAME, required=True)
        scope = self.clean_scope(raw)
        days = raw.get("expires_days", DEFAULT_EXPIRY_DAYS)
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= MAX_EXPIRY_DAYS:
            raise GuestError("invalid", 422)
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
        }
        self.invites[invite["id"]] = invite
        if not self.vapid:
            self.vapid = await self.hass.async_add_executor_job(webpush.generate_keys)
        self._record("invite_created", name)
        await self.async_save()
        guest_hub(self.hass).ensure_views()
        return invite, token

    async def async_revoke_invite(self, invite_id: str) -> None:
        invite = self.invites.get(invite_id)
        if invite is None:
            raise GuestError("not_found", 404)
        if invite["status"] == OPEN:
            invite["status"] = REVOKED
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
            "push": None,
        }
        invite["status"] = USED
        invite["device_id"] = device["id"]
        invite["token_hash"] = None
        self.devices[device["id"]] = device
        self._record("activated", device["name"], device["label"])
        await self.async_save()
        self._spawn(self._tell_adults_device(device))
        return token

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

    async def async_confirm(self, device_id: str, accept: bool) -> dict[str, Any]:
        device = self._device(device_id)
        if device["status"] != PENDING:
            raise GuestError("not_pending", 409)
        device["status"] = ACTIVE if accept else REJECTED
        if not accept:
            device["push"] = None
        self._record("confirmed" if accept else "rejected", device["name"], device["label"])
        persistent_notification.async_dismiss(self.hass, f"{DOMAIN}_guest_{device_id}")
        await self.async_save()
        return device

    async def async_update_device(self, device_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        device = self._device(device_id)
        if device["status"] in (REJECTED, DISABLED):
            raise GuestError("not_active", 409)
        if "name" in raw:
            name = _text(raw.get("name"), MAX_NAME, required=True)
            if name != device["name"]:
                self._record("renamed", name, device["name"])
                device["name"] = name
        if any(key in raw for key in ("persons", "categories", "permission", "approval", "notify")):
            scope = self.clean_scope({**device, **raw})
            device.update(scope)
            if not scope["notify"]:
                device["push"] = None
            self._record("permissions", device["name"])
        await self.async_save()
        return device

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

    async def async_remove_device(self, device_id: str) -> None:
        """Forget a device that is already off (disabled or rejected)."""
        device = self._device(device_id)
        if device["status"] not in (DISABLED, REJECTED):
            raise GuestError("still_active", 409)
        del self.devices[device_id]
        await self.async_save()

    # ----- what a guest sees ------------------------------------------------

    @staticmethod
    def visible(record: dict[str, Any], device: dict[str, Any]) -> bool:
        """An appointment of an allowed calendar with at least one allowed person."""
        if record.get("category") not in device["categories"]:
            return False
        return bool(set(record.get("persons") or []) & set(device["persons"]))

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
            "persons": [p for p in record.get("persons") or [] if p in device["persons"]],
            "location": record.get("location") or "",
            "added_by": str(added.get("name") or "") if isinstance(added, dict) else "",
            "mine": mine,
            "status": status,
        }
        if mine:
            item["note"] = record.get("description") or ""
        return item

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
                "vapid": self.vapid.get("public", "") if device["notify"] else "",
                "language": self.language,
                "first_weekday": str(options.get(CONF_FIRST_WEEKDAY) or "monday"),
                "time_format": str(options.get(CONF_TIME_FORMAT) or "24h"),
                "persons": [
                    {
                        "id": pid,
                        "name": str(persons[pid].get("name", "")),
                        "color": str(persons[pid].get("color") or ""),
                    }
                    for pid in device["persons"]
                    if pid in persons
                ],
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

    def list_events(self, device: dict[str, Any], start: date, days: int) -> list[dict[str, Any]]:
        """The device's appointments that overlap ``days`` days from ``start``, filtered here."""
        self.check_active(device)
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

    # ----- appointments from a guest ---------------------------------------

    def _today(self) -> date:
        return dt_util.as_local(dt_util.now()).date()

    async def async_guest_add(self, device: dict[str, Any], raw: Any) -> dict[str, Any]:
        self.check_active(device)
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
        self.check_active(device)
        if device["permission"] != EDIT_OWN:
            raise GuestError("forbidden", 403)
        kind, current = self._own(device, item_id)
        event = clean_event(raw, device["persons"], device["categories"], self._today())
        if kind == "pending":
            self.pending[item_id]["event"] = {**event, "added_by": current.get("added_by")}
            self._record("event_changed", device["name"], event["summary"])
            await self.async_save()
            return self.guest_event(
                {"uid": item_id, **self.pending[item_id]["event"]}, device, status="pending"
            )
        added_by = dict(current.get("added_by") or {})
        if event["category"] != current["category"]:
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
                await calendar.async_update_event(uid, change)
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

    async def async_guest_delete(self, device: dict[str, Any], item_id: str) -> None:
        self.check_active(device)
        if device["permission"] != EDIT_OWN:
            raise GuestError("forbidden", 403)
        kind, current = self._own(device, item_id)
        if kind == "pending":
            del self.pending[item_id]
        else:
            await self._delete_record(current, device["id"])
        self._record("event_deleted", device["name"], str(current.get("summary", "")))
        await self.async_save()

    # ----- approval (adults) ------------------------------------------------

    async def async_approve(
        self, item_id: str, accept: bool, changes: dict[str, Any] | None = None
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
                event = {**cleaned, "added_by": event.get("added_by")}
            uid = await self._write(event, dict(event.get("added_by") or {}), None)
        del self.pending[item_id]
        self._record("approved" if accept else "declined", name, str(event["summary"]))
        persistent_notification.async_dismiss(self.hass, f"{DOMAIN}_guest_{item_id}")
        await self.async_save()
        if device is not None and device["status"] == ACTIVE:
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

    def _adult_phones(self) -> list[str]:
        phones = [
            str(p["phone_notify"])
            for p in self.entry.options.get(OPT_PERSONS, [])
            if p.get("role", "adult") == "adult" and p.get("phone_notify")
        ]
        return list(dict.fromkeys(phones))

    async def _notify_adults(
        self,
        notification_id: str,
        phone_message: str,
        tablet_message: str,
        actions: list[dict[str, str]],
    ) -> None:
        text = texts_for(self.language)
        persistent_notification.async_create(
            self.hass, tablet_message, title=text["title"], notification_id=notification_id
        )
        for phone in self._adult_phones():
            if not self.hass.services.has_service("notify", phone):
                continue
            try:
                await self.hass.services.async_call(
                    "notify",
                    phone,
                    {
                        "title": text["title"],
                        "message": phone_message,
                        "data": {"tag": notification_id, "actions": actions},
                    },
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
        )

    async def async_handle_action(self, action: str) -> bool:
        """A button on an adult's phone: FH_GUEST_<CONFIRM|REJECT|APPROVE|DECLINE>_<id>.
        True when the action was one of this family's."""
        command, _, item_id = action.removeprefix(ACTION_PREFIX).partition("_")
        try:
            if command in ("CONFIRM", "REJECT") and item_id in self.devices:
                await self.async_confirm(item_id, command == "CONFIRM")
                return True
            if command in ("APPROVE", "DECLINE") and item_id in self.pending:
                await self.async_approve(item_id, command == "APPROVE")
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
        if not subscription or not device["notify"] or not self.vapid:
            return
        result = await webpush.async_send(
            self.hass, subscription, payload, self.vapid["private"], self._subject()
        )
        if result == webpush.GONE:
            device["push"] = None
            await self._store.async_save(self._data())

    async def async_set_push(self, device: dict[str, Any], raw: Any) -> bool:
        self.check_active(device)
        if raw is None:
            device["push"] = None
        else:
            if not device["notify"]:
                raise GuestError("forbidden", 403)
            subscription = webpush.clean_subscription(raw)
            if subscription is None:
                raise GuestError("invalid", 422)
            device["push"] = subscription
        await self._store.async_save(self._data())
        return device["push"] is not None

    def _listeners(self) -> list[dict[str, Any]]:
        return [
            d
            for d in self.devices.values()
            if d["status"] == ACTIVE and d["notify"] and d.get("push")
        ]

    def _quiet_now(self) -> bool:
        from .reminders import _clock, in_quiet_hours  # noqa: PLC0415

        settings = {**DEFAULT_REMINDERS, **self.entry.options.get(OPT_REMINDERS, {})}
        now = dt_util.as_local(dt_util.now()).time()
        return in_quiet_hours(now, _clock(settings["quiet_start"]), _clock(settings["quiet_end"]))

    async def async_on_reminder(self, record: dict[str, Any], message: str) -> None:
        """A family reminder went out: guests who see the appointment get it too, at the same
        moment, outside the family's quiet hours."""
        listeners = [d for d in self._listeners() if self.visible(record, d)]
        if not listeners or self._quiet_now():
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
        )

    async def async_store_changed(self) -> None:
        """After every save of the appointments: guests hear about changes and cancellations of
        appointments they can see (not about their own changes, nor past appointments)."""
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
        text = texts_for(self.language)
        for device in self._listeners():
            if device["id"] == self._changing:
                continue
            messages: list[str] = []
            for uid in gone:
                before = old_records[uid]
                if self.visible(before, device) and _start_of(before) > now:
                    title = before["summary"]
                    messages.append(text["cancelled"].format(title=title, when=self._when(before)))
            for uid in changed:
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
                    )
                }
                | {"status": status}
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
            | {"push": device.get("push") is not None}
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
                }
            )
        return {
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
