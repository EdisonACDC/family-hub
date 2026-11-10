"""Websocket commands for the setup guide of the tablet add-on.

``family_hub/config/get`` and ``family_hub/config/save`` read and write the whole family
configuration (family, persons, categories, reminders, screen). Saving uses the same rules as
the options flow. Both need an administrator, so only the add-on (which checks the role of
the person in front of the screen) can call them.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from typing import Any

import probatio as vol  # Home Assistant's schema library (voluptuous successor).
from homeassistant.components.websocket_api import async_register_command
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.components.websocket_api.decorators import (
    async_response,
    require_admin,
    websocket_command,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration

from .config_flow import _bad_time
from .const import (
    ALEXA_ALL,
    CHANNELS,
    CONF_ALEXA_VOLUME,
    CONF_CHANNELS,
    CONF_COUNTRY,
    CONF_FAMILY_NAME,
    CONF_FIRST_WEEKDAY,
    CONF_HA_USER,
    CONF_LANGUAGE,
    CONF_PHONE_SOUND,
    CONF_REGION,
    CONF_THEME,
    CONF_TIME_FORMAT,
    CONF_WEEK_FROM_TODAY,
    DEFAULT_PHONE_SOUND,
    DEFAULT_REMINDERS,
    DOMAIN,
    LANGUAGES,
    OPT_CATEGORIES,
    OPT_PERSONS,
    OPT_REMINDERS,
    OPT_SHARED_USERS,
    OPT_SHIFTS,
    PERSON_CHANNELS,
    PHONE_SOUNDS,
    ROLES,
    SUMMARY_CHANNELS,
    THEMES,
    TIME_FORMATS,
    WEEKDAYS,
)
from .external import TYPES as ICS_TYPES
from .external_api import async_register_external_commands
from .notifier import announce_on_echos, phone_os, sound_data, texts_for
from .notify_settings import alexa_targets, available_services, echo_entities
from .shifts import ShiftError, apply_to_future, clean_shifts

PERSON_TEXT_KEYS = (
    "phone_notify",
    "speaker",
    "alexa_notify",
    "ha_user_id",
    "quiet_start",
    "quiet_end",
    "all_day_reminder",
)
TIME_KEYS = ("quiet_start", "quiet_end", "all_day_reminder")
# Set when the guide saves: "configured" is read from here, not from the browser.
SETUP_DONE = "setup_done"


class ConfigError(ValueError):
    """The configuration sent by the guide is not valid. ``code`` is the websocket error code."""

    def __init__(self, message: str, code: str = "invalid_config") -> None:
        super().__init__(message)
        self.code = code


def _obj(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{field}: must be an object")
    return value


def _items(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ConfigError(f"{field}: must be a list of objects")
    return value


def _text(value: Any, field: str, *, max_len: int = 60, required: bool = False) -> str:
    text = "" if value is None else str(value).strip()
    if required and not text:
        raise ConfigError(f"{field}: required")
    if len(text) > max_len:
        raise ConfigError(f"{field}: too long")
    return text


def _color(value: Any, field: str) -> str:
    text = _text(value, field, max_len=7, required=True)
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", text):
        raise ConfigError(f"{field}: not a colour")
    return text


def _time(value: Any, field: str) -> str:
    text = _text(value, field, max_len=5)
    if _bad_time(text):
        raise ConfigError(f"{field}: not HH:MM")
    return text


def _choice(value: Any, allowed: list[str], field: str) -> str:
    if value not in allowed:
        raise ConfigError(f"{field}: not one of {', '.join(allowed)}")
    return str(value)


def _flag(value: Any, default: bool) -> bool:
    """A yes/no setting. A missing or non-boolean value keeps the default."""
    return value if isinstance(value, bool) else default


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or uuid.uuid4().hex[:8]


# Entities the guide may add besides the Family Hub calendars: to-do lists and other calendars.
# Wildcards are not accepted: each entity is listed by its full id.
SOURCE_DOMAINS = {"todo": "todo.", "calendars": "calendar.", "weather": "weather."}


def is_family_entity(hass: HomeAssistant, entity_id: str) -> bool:
    """True for an entity Family Hub made, found in the entity registry (never by its name)."""
    entry = er.async_get(hass).async_get(entity_id)
    return entry is not None and entry.platform == DOMAIN


def _sources(
    value: Any,
    known: Callable[[str], bool],
    person_ids: set[str] | None = None,
    is_family: Callable[[str], bool] = lambda entity_id: False,
) -> dict[str, Any]:
    raw = _obj(value, "sources")
    result: dict[str, Any] = {}
    for key, prefix in SOURCE_DOMAINS.items():
        items = raw.get(key, [])
        if not isinstance(items, list) or not all(isinstance(e, str) for e in items):
            raise ConfigError(f"sources.{key}: must be a list of entity ids")
        for entity_id in items:
            if not entity_id.startswith(prefix) or is_family(entity_id):
                raise ConfigError(f"sources.{key}: {entity_id} is not a {prefix[:-1]} entity")
            if not known(entity_id):
                raise ConfigError(f"sources.{key}: {entity_id} does not exist")
        result[key] = list(dict.fromkeys(items))
    if len(result.get("weather", [])) > 1:
        raise ConfigError("sources.weather: choose one weather entity")
    result["calendar_styles"] = _calendar_styles(
        raw.get("calendar_styles", {}), result["calendars"], person_ids
    )
    return result


def _calendar_styles(
    value: Any, calendars: list[str], person_ids: set[str] | None = None
) -> dict[str, dict[str, Any]]:
    """How a calendar of Home Assistant looks in Family Hub: its shown name, its type (rubbish,
    holidays, ...), its colour and the persons it belongs to (calendar.mamma -> Mamma). Only the
    chosen source calendars can have one. Persons that no longer exist are dropped."""
    raw = _obj(value, "sources.calendar_styles")
    styles: dict[str, dict[str, Any]] = {}
    for entity_id, style in raw.items():
        if entity_id not in calendars:
            # A style left over from a calendar that was unticked: dropped, not an error.
            continue
        style = _obj(style, f"sources.calendar_styles.{entity_id}")
        kind = str(style.get("type") or "altro")
        if kind not in ICS_TYPES:
            raise ConfigError(f"sources.calendar_styles.{entity_id}.type: unknown type")
        styles[entity_id] = {
            "name": _text(style.get("name"), f"sources.calendar_styles.{entity_id}.name"),
            "type": kind,
            "color": _color(
                style.get("color") or "#64748B", f"sources.calendar_styles.{entity_id}.color"
            ),
            "persons": _style_persons(style.get("persons", []), entity_id, person_ids),
        }
    return styles


def _style_persons(value: Any, entity_id: str, person_ids: set[str] | None) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(p, str) for p in value):
        raise ConfigError(f"sources.calendar_styles.{entity_id}.persons: a list of person ids")
    chosen = list(dict.fromkeys(value))
    if person_ids is not None:
        chosen = [p for p in chosen if p in person_ids]
    return chosen


def clean_config(
    config: dict[str, Any],
    current: dict[str, Any],
    in_use: dict[str, str] | None = None,
    known: Callable[[str], bool] = lambda entity_id: True,
    available: dict[str, list[str]] | None = None,
    is_family: Callable[[str], bool] = lambda entity_id: False,
) -> dict[str, Any]:
    """Validate a configuration and return the options to store. Raises ConfigError.

    ``in_use`` maps category ids that still have events to their names: such a category
    cannot be removed, as in the options flow. ``available`` lists the notification services
    that exist now; when given, a person can only be set to one of them.
    """
    family = _obj(config.get("family", {}), "family")
    screen = _obj(config.get("screen", {}), "screen")
    reminders = _obj(config.get("reminders", {}), "reminders")

    options: dict[str, Any] = {
        CONF_FAMILY_NAME: _text(family.get(CONF_FAMILY_NAME), CONF_FAMILY_NAME, required=True),
        CONF_LANGUAGE: _choice(family.get(CONF_LANGUAGE), LANGUAGES, CONF_LANGUAGE),
        CONF_FIRST_WEEKDAY: _choice(family.get(CONF_FIRST_WEEKDAY), WEEKDAYS, CONF_FIRST_WEEKDAY),
        CONF_TIME_FORMAT: _choice(family.get(CONF_TIME_FORMAT), TIME_FORMATS, CONF_TIME_FORMAT),
        CONF_COUNTRY: _text(family.get(CONF_COUNTRY), CONF_COUNTRY),
        CONF_REGION: _text(family.get(CONF_REGION), CONF_REGION),
        CONF_THEME: _choice(screen.get(CONF_THEME), THEMES, CONF_THEME),
        CONF_WEEK_FROM_TODAY: _flag(screen.get(CONF_WEEK_FROM_TODAY), True),
    }

    persons = []
    for index, raw in enumerate(_items(config.get("persons", []), "persons")):
        person = clean_person(raw, f"persons[{index}]", available)
        persons.append(person)
    if len({p["id"] for p in persons}) != len(persons):
        raise ConfigError("persons: duplicate id")
    _check_unique_users(persons)
    options[OPT_PERSONS] = persons
    # Kept when the configuration does not mention them, so a save never drops the shared screens.
    options[OPT_SHARED_USERS] = clean_shared_users(
        config.get("shared_users", current.get(OPT_SHARED_USERS, [])), persons
    )

    categories = []
    for index, raw in enumerate(_items(config.get("categories", []), "categories")):
        field = f"categories[{index}]"
        name = _text(raw.get("name"), f"{field}.name", required=True)
        categories.append(
            {
                "id": str(raw.get("id") or _slug(name)),
                "name": name,
                "color": _color(raw.get("color"), f"{field}.color"),
            }
        )
    if not categories:
        raise ConfigError("categories: at least one is needed")
    kept = {c["id"] for c in categories}
    for category_id, name in (in_use or {}).items():
        if category_id not in kept:
            raise ConfigError(f"category_in_use: {name} still has events", "category_in_use")
    if len({c["id"] for c in categories}) != len(categories):
        raise ConfigError("categories: duplicate name")
    options[OPT_CATEGORIES] = categories

    offsets = reminders.get("offsets", DEFAULT_REMINDERS["offsets"])
    if not isinstance(offsets, list) or not all(
        isinstance(o, int) and not isinstance(o, bool) and 0 <= o <= 1440 for o in offsets
    ):
        raise ConfigError("reminders.offsets: whole minutes from 0 to 1440")
    channels = reminders.get("channels", DEFAULT_REMINDERS["channels"])
    if not isinstance(channels, list) or not all(c in CHANNELS for c in channels):
        raise ConfigError("reminders.channels: unknown channel")
    snooze = reminders.get("snooze_minutes", DEFAULT_REMINDERS["snooze_minutes"])
    if not isinstance(snooze, int) or isinstance(snooze, bool) or not 1 <= snooze <= 1440:
        raise ConfigError("reminders.snooze_minutes: 1 to 1440")
    summary_channels = reminders.get("summary_channels", DEFAULT_REMINDERS["summary_channels"])
    if not isinstance(summary_channels, list) or not all(
        c in SUMMARY_CHANNELS for c in summary_channels
    ):
        raise ConfigError("reminders.summary_channels: phone, alexa or tablet")
    options[OPT_REMINDERS] = {
        "offsets": offsets,
        "morning_summary_on": bool(reminders.get("morning_summary_on", True)),
        "evening_summary_on": bool(reminders.get("evening_summary_on", True)),
        "summary_channels": list(dict.fromkeys(summary_channels)),
        "channels": list(channels),
        "quiet_start": _time(reminders.get("quiet_start"), "reminders.quiet_start"),
        "quiet_end": _time(reminders.get("quiet_end"), "reminders.quiet_end"),
        "snooze_minutes": snooze,
        "tts_entity": _text(reminders.get("tts_entity"), "reminders.tts_entity", max_len=255)
        or None,
        "morning_summary": _time(reminders.get("morning_summary"), "reminders.morning_summary")
        or None,
        "evening_summary": _time(reminders.get("evening_summary"), "reminders.evening_summary")
        or None,
        "all_day_reminder": _time(reminders.get("all_day_reminder"), "reminders.all_day_reminder")
        or None,
    }
    options["sources"] = _sources(
        config.get("sources", {}),
        known,
        {str(p["id"]) for p in options[OPT_PERSONS]},
        is_family,
    )
    options[SETUP_DONE] = True
    return {**current, **options}


def clean_person(
    raw: dict[str, Any], field: str, available: dict[str, list[str]] | None
) -> dict[str, Any]:
    """One person, as stored. ``available`` is checked when given: a phone or Echo service
    that does not exist in Home Assistant is refused."""
    person: dict[str, Any] = {
        "id": str(raw.get("id") or uuid.uuid4().hex[:8]),
        "name": _text(raw.get("name"), f"{field}.name", required=True),
        "color": _color(raw.get("color"), f"{field}.color"),
        "role": _choice(raw.get("role"), ROLES, f"{field}.role"),
    }
    for key in PERSON_TEXT_KEYS:
        value = _text(raw.get(key), f"{field}.{key}", max_len=120)
        if key in TIME_KEYS:
            value = _time(value, f"{field}.{key}") if value else ""
        if value:
            person[key] = value
    if available is not None:
        phone = person.get("phone_notify")
        if phone and phone not in available["phone"]:
            raise ConfigError(
                f"{field}.phone_notify: {phone} is not a phone service in Home Assistant",
                "unknown_service",
            )
        echo = person.get("alexa_notify")
        if echo and echo != ALEXA_ALL and echo not in available["alexa"]:
            raise ConfigError(
                f"{field}.alexa_notify: {echo} is not an Echo service in Home Assistant",
                "unknown_service",
            )
    channels = raw.get(CONF_CHANNELS)
    if channels is None:
        channels = list(PERSON_CHANNELS)
    if not isinstance(channels, list) or not all(c in PERSON_CHANNELS for c in channels):
        raise ConfigError(f"{field}.channels: unknown channel")
    person[CONF_CHANNELS] = list(dict.fromkeys(channels))
    volume = raw.get(CONF_ALEXA_VOLUME)
    if volume not in (None, ""):
        if isinstance(volume, bool) or not isinstance(volume, int) or not 0 <= volume <= 100:
            raise ConfigError(f"{field}.alexa_volume: whole number from 0 to 100")
        person[CONF_ALEXA_VOLUME] = volume
    sound = raw.get(CONF_PHONE_SOUND)
    if sound not in (None, ""):
        if sound not in PHONE_SOUNDS:
            raise ConfigError(f"{field}.phone_sound: normal, important or critical")
        person[CONF_PHONE_SOUND] = sound
    return person


def _check_unique_users(persons: list[dict[str, Any]]) -> None:
    """One Home Assistant user can stand for one person only."""
    users = [p[CONF_HA_USER] for p in persons if p.get(CONF_HA_USER)]
    if len(set(users)) != len(users):
        raise ConfigError("persons: a Home Assistant user is linked to two persons")


# The fields the "Avvisi" page may change. Name, colour and role stay in the guide.
NOTIFY_KEYS = (
    CONF_HA_USER,
    "phone_notify",
    "alexa_notify",
    CONF_ALEXA_VOLUME,
    CONF_PHONE_SOUND,
    CONF_CHANNELS,
    "quiet_start",
    "quiet_end",
)


def describe(options: dict[str, Any]) -> dict[str, Any]:
    """The configuration as the guide reads it."""
    return {
        "configured": bool(options.get(SETUP_DONE, False)),
        "sources": {
            "todo": list(options.get("sources", {}).get("todo", [])),
            "calendars": list(options.get("sources", {}).get("calendars", [])),
            "calendar_styles": dict(options.get("sources", {}).get("calendar_styles", {})),
            "weather": list(options.get("sources", {}).get("weather", [])),
        },
        "family": {
            CONF_FAMILY_NAME: options.get(CONF_FAMILY_NAME, ""),
            CONF_LANGUAGE: options.get(CONF_LANGUAGE, "en"),
            CONF_FIRST_WEEKDAY: options.get(CONF_FIRST_WEEKDAY, "monday"),
            CONF_TIME_FORMAT: options.get(CONF_TIME_FORMAT, "24h"),
            CONF_COUNTRY: options.get(CONF_COUNTRY, ""),
            CONF_REGION: options.get(CONF_REGION, ""),
        },
        "screen": {
            CONF_THEME: options.get(CONF_THEME, "auto"),
            CONF_WEEK_FROM_TODAY: options.get(CONF_WEEK_FROM_TODAY, True),
        },
        "shifts": dict(options.get(OPT_SHIFTS, {})),
        "persons": list(options.get(OPT_PERSONS, [])),
        "shared_users": list(options.get(OPT_SHARED_USERS, [])),
        "categories": list(options.get(OPT_CATEGORIES, [])),
        "reminders": {**DEFAULT_REMINDERS, **options.get(OPT_REMINDERS, {})},
    }


def _categories_in_use(entry: ConfigEntry) -> dict[str, str]:
    """Category id -> name, for categories that have at least one event stored."""
    data = getattr(entry, "runtime_data", None)
    if data is None:
        return {}
    used = {record["category"] for record in data.store.events.values()}
    for shifts in entry.options.get(OPT_SHIFTS, {}).values():
        used.update(shift["category"] for shift in shifts)
    names = {c["id"]: c.get("name", c["id"]) for c in entry.options.get(OPT_CATEGORIES, [])}
    return {category_id: names.get(category_id, category_id) for category_id in used}


def _entry(hass: HomeAssistant, entry_id: str | None) -> ConfigEntry | None:
    entries = hass.config_entries.async_entries(DOMAIN)
    if entry_id is not None:
        return next((e for e in entries if e.entry_id == entry_id), None)
    return entries[0] if len(entries) == 1 else None


@websocket_command({vol.Required("type"): "family_hub/info"})
@async_response
async def ws_info(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """The integration's version and whether Family Hub is set up. Any signed-in user may ask:
    it holds no family data. The tablet add-on uses it to say what is missing or out of date."""
    integration = await async_get_integration(hass, DOMAIN)
    connection.send_result(
        msg["id"],
        {
            "version": str(integration.version),
            "configured": _entry(hass, None) is not None,
            # Home Assistant's language: the page uses it until the family has chosen one.
            "language": str(hass.config.language or ""),
        },
    )


@require_admin
@websocket_command({vol.Required("type"): "family_hub/config/get", vol.Optional("entry_id"): str})
@async_response
async def ws_config_get(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the family configuration."""
    entry = _entry(hass, msg.get("entry_id"))
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Family Hub is not set up")
        return
    connection.send_result(msg["id"], describe(dict(entry.options)))


@require_admin
@websocket_command(
    {
        vol.Required("type"): "family_hub/config/save",
        vol.Optional("entry_id"): str,
        vol.Required("config"): dict,
    }
)
@async_response
async def ws_config_save(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Validate and store the family configuration. The entry reloads afterwards."""
    entry = _entry(hass, msg.get("entry_id"))
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Family Hub is not set up")
        return
    try:
        options = clean_config(
            msg["config"],
            dict(entry.options),
            _categories_in_use(entry),
            lambda entity_id: hass.states.get(entity_id) is not None,
            available_services(hass),
            lambda entity_id: is_family_entity(hass, entity_id),
        )
    except ConfigError as err:
        connection.send_error(msg["id"], err.code, str(err))
        return
    hass.config_entries.async_update_entry(entry, options=options)
    connection.send_result(msg["id"], {"saved": True})


@require_admin
@websocket_command(
    {
        vol.Required("type"): "family_hub/notify/save",
        vol.Optional("entry_id"): str,
        vol.Required("persons"): dict,
    }
)
@async_response
async def ws_notify_save(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Save the notification settings of some persons (the "Avvisi" page).

    Only the fields in NOTIFY_KEYS change. Services must exist in Home Assistant now.
    The add-on decides who may change whose settings.
    """
    entry = _entry(hass, msg.get("entry_id"))
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Family Hub is not set up")
        return
    current = list(entry.options.get(OPT_PERSONS, []))
    by_id = {p["id"]: p for p in current}
    available = available_services(hass)
    try:
        changed: dict[str, dict[str, Any]] = {}
        for person_id, raw_changes in msg["persons"].items():
            if person_id not in by_id:
                raise ConfigError("Unknown person", "not_found")
            stored = by_id[person_id]
            changes = {k: v for k, v in _obj(raw_changes, person_id).items() if k in NOTIFY_KEYS}
            merged = {**stored, **{k: changes.get(k, stored.get(k)) for k in NOTIFY_KEYS}}
            # A service the person already has is kept even if it has gone missing since;
            # only a newly chosen one must exist.
            known = {
                "phone": [*available["phone"], *_kept(stored, "phone_notify")],
                "alexa": [*available["alexa"], *_kept(stored, "alexa_notify")],
            }
            changed[person_id] = clean_person(merged, f"persons[{person_id}]", known)
        persons = [changed.get(p["id"], p) for p in current]
        _check_unique_users(persons)
    except ConfigError as err:
        connection.send_error(msg["id"], err.code, str(err))
        return
    hass.config_entries.async_update_entry(entry, options={**entry.options, OPT_PERSONS: persons})
    connection.send_result(msg["id"], {"saved": True})


def _shift_key(shift: dict[str, str]) -> tuple[str, str, str, str]:
    return (shift["name"], shift["start"], shift["end"], shift["category"])


@require_admin
@websocket_command(
    {
        vol.Required("type"): "family_hub/shifts/save",
        vol.Optional("entry_id"): str,
        vol.Required("person"): str,
        vol.Required("shifts"): list,
        vol.Optional("apply_future", default=False): bool,
    }
)
@async_response
async def ws_shifts_save(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Save the shift models of one person. Only the models change, not the rest of the setup.

    Home Assistant admin is required; the add-on's Supervisor token is admin, and the add-on
    checks who may change which person's shifts. With ``apply_future``, events already entered
    from a changed model are updated from tomorrow on; past events never change.
    """
    entry = _entry(hass, msg.get("entry_id"))
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Family Hub is not set up")
        return
    person = msg["person"]
    if person not in {p["id"] for p in entry.options.get(OPT_PERSONS, [])}:
        connection.send_error(msg["id"], "not_found", "Unknown person")
        return
    categories = {c["id"] for c in entry.options.get(OPT_CATEGORIES, [])}
    try:
        cleaned = clean_shifts(msg["shifts"], categories)
    except ShiftError as err:
        connection.send_error(msg["id"], "invalid_config", str(err))
        return
    all_shifts = dict(entry.options.get(OPT_SHIFTS, {}))
    old = {s["id"]: s for s in all_shifts.get(person, [])}
    changes = {
        s["id"]: s for s in cleaned if s["id"] in old and _shift_key(s) != _shift_key(old[s["id"]])
    }
    updated = 0
    if changes and msg.get("apply_future"):
        updated = await apply_to_future(entry, changes, person)
    all_shifts[person] = cleaned
    hass.config_entries.async_update_entry(entry, options={**entry.options, OPT_SHIFTS: all_shifts})
    connection.send_result(msg["id"], {"saved": True, "updated": updated})


def _kept(stored: dict[str, Any], key: str) -> list[str]:
    value = stored.get(key)
    return [value] if value else []


@require_admin
@websocket_command(
    {
        vol.Required("type"): "family_hub/notify/test",
        vol.Optional("entry_id"): str,
        vol.Required("person"): str,
        vol.Required("kind"): str,
        # The choice and volume on the screen, when they are not saved yet ("Prova Echo" uses
        # what is shown). Without them, the saved ones are used.
        vol.Optional("alexa_notify"): str,
        vol.Optional("alexa_volume"): object,
    }
)
@async_response
async def ws_notify_test(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Send a test message to one person's chosen phone or Echo speakers, and nothing else.

    A phone test goes to the person's phone service. An Echo test follows the speakers and the
    volume on the screen (or, without them, the saved ones), as a reminder does.
    """
    entry = _entry(hass, msg.get("entry_id"))
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Family Hub is not set up")
        return
    person = next((p for p in entry.options.get(OPT_PERSONS, []) if p["id"] == msg["person"]), None)
    if person is None:
        connection.send_error(msg["id"], "not_found", "Unknown person")
        return
    kind = msg["kind"]
    if kind == "phone":
        phone = person.get("phone_notify") or ""
        if phone not in available_services(hass)["phone"]:
            connection.send_error(msg["id"], "no_service", "No phone is chosen")
            return
        # The test sounds as the reminders will.
        language = str(entry.options.get(CONF_LANGUAGE) or "en")
        sound = sound_data(
            person.get(CONF_PHONE_SOUND) or DEFAULT_PHONE_SOUND, phone_os(hass, phone), language
        )
        test_text = texts_for(language)["test"]
        payload: dict[str, Any] = {"title": "Family Hub", "message": test_text}
        if sound:
            payload["data"] = sound
        await hass.services.async_call("notify", phone, payload, blocking=True)
        connection.send_result(msg["id"], {"sent": 1})
        return
    if kind == "alexa":
        choice = msg["alexa_notify"] if "alexa_notify" in msg else person.get("alexa_notify") or ""
        volume = msg["alexa_volume"] if "alexa_volume" in msg else person.get("alexa_volume")
        # The same rules as saving: a whole number 0 to 100 (or none), and an Echo that exists.
        if volume is not None and (
            isinstance(volume, bool) or not isinstance(volume, int) or not 0 <= volume <= 100
        ):
            connection.send_error(msg["id"], "bad_request", "Volume: whole number from 0 to 100")
            return
        if choice and choice != ALEXA_ALL and choice not in echo_entities(hass):
            connection.send_error(msg["id"], "unknown_service", "Not an Echo in Home Assistant")
            return
        speakers = alexa_targets(hass, choice)
        if not speakers:
            connection.send_error(msg["id"], "no_service", "No Echo is chosen")
            return
        test_text = texts_for(str(entry.options.get(CONF_LANGUAGE) or "en"))["test"]
        await announce_on_echos(hass, speakers, test_text, volume)
        connection.send_result(msg["id"], {"sent": len(speakers)})
        return
    connection.send_error(msg["id"], "bad_request", "Unknown kind")


def clean_shared_users(users: Any, persons: list[dict[str, Any]]) -> list[str]:
    """Home Assistant users that are shared screens. A user linked to a person is never one."""
    if not isinstance(users, list) or not all(isinstance(u, str) and u for u in users):
        raise ConfigError("shared_users: list of Home Assistant user ids")
    linked = {p.get(CONF_HA_USER) for p in persons if p.get(CONF_HA_USER)}
    return list(dict.fromkeys(u for u in users if u not in linked))


@require_admin
@websocket_command(
    {
        vol.Required("type"): "family_hub/shared/save",
        vol.Optional("entry_id"): str,
        vol.Required("users"): [str],
    }
)
@async_response
async def ws_shared_save(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Save which Home Assistant users are shared screens (the "Schermi condivisi" list)."""
    entry = _entry(hass, msg.get("entry_id"))
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Family Hub is not set up")
        return
    try:
        users = clean_shared_users(msg["users"], list(entry.options.get(OPT_PERSONS, [])))
    except ConfigError as err:
        connection.send_error(msg["id"], err.code, str(err))
        return
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, OPT_SHARED_USERS: users}
    )
    connection.send_result(msg["id"], {"saved": True, "users": users})


@require_admin
@websocket_command(
    {
        vol.Required("type"): "family_hub/summary/save",
        vol.Optional("entry_id"): str,
        vol.Required("reminders"): dict,
    }
)
@async_response
async def ws_summary_save(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Save the morning and evening summaries: their times, their switches and the channels they
    go on. A switch off keeps the time. Only these keys change."""
    entry = _entry(hass, msg.get("entry_id"))
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Family Hub is not set up")
        return
    raw = msg["reminders"]
    reminders = dict(entry.options.get(OPT_REMINDERS, {}))
    try:
        for kind in ("morning", "evening"):
            if f"{kind}_summary" in raw:
                reminders[f"{kind}_summary"] = (
                    _time(raw[f"{kind}_summary"], f"reminders.{kind}_summary") or None
                )
            if f"{kind}_summary_on" in raw:
                reminders[f"{kind}_summary_on"] = bool(raw[f"{kind}_summary_on"])
        if "summary_channels" in raw:
            channels = raw["summary_channels"]
            if not isinstance(channels, list) or not all(c in SUMMARY_CHANNELS for c in channels):
                raise ConfigError("reminders.summary_channels: phone, alexa or tablet")
            reminders["summary_channels"] = list(dict.fromkeys(channels))
    except ConfigError as err:
        connection.send_error(msg["id"], err.code, str(err))
        return
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, OPT_REMINDERS: reminders}
    )
    connection.send_result(msg["id"], {"saved": True})


@callback
def async_register_commands(hass: HomeAssistant) -> None:
    """Register the websocket commands once."""
    async_register_command(hass, ws_info)
    async_register_command(hass, ws_config_get)
    async_register_command(hass, ws_config_save)
    async_register_command(hass, ws_shifts_save)
    async_register_command(hass, ws_notify_save)
    async_register_command(hass, ws_notify_test)
    async_register_command(hass, ws_summary_save)
    async_register_command(hass, ws_shared_save)
    async_register_external_commands(hass)
