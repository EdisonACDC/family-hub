"""Constants for the Family Hub integration."""

from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any, Final

DOMAIN: Final = "family_hub"
STORAGE_VERSION: Final = 1

# Entry data (set once in the config flow).
CONF_FAMILY_NAME: Final = "family_name"
CONF_LANGUAGE: Final = "language"
CONF_FIRST_WEEKDAY: Final = "first_weekday"

# Entry options (editable in the options flow). Persons and categories live here,
# so the whole configuration is one list per kind and no name is hard-coded.
OPT_PERSONS: Final = "persons"
OPT_CATEGORIES: Final = "categories"
# Home Assistant users that are shared screens (not linked to a person): they may add,
# change and tick events and lists, but not open the settings.
OPT_SHARED_USERS: Final = "shared_users"

LANGUAGES: Final[list[str]] = ["it", "de", "en"]
# Family settings, kept in the entry options since config entry version 2.
CONF_COUNTRY: Final = "country"
CONF_REGION: Final = "region"
CONF_TIME_FORMAT: Final = "time_format"
CONF_THEME: Final = "theme"
# On the wall tablet the week starts today (today + 6 days) instead of the family's first day.
CONF_WEEK_FROM_TODAY: Final = "week_from_today"
TIME_FORMATS: Final[list[str]] = ["24h", "12h"]
THEMES: Final[list[str]] = ["auto", "light", "dark"]
WEEKDAYS: Final[list[str]] = ["monday", "sunday"]
ROLES: Final[list[str]] = ["adult", "child", "guest"]

CATEGORY_NAMES: Final[dict[str, dict[str, str]]] = {
    "it": {
        "famiglia": "Famiglia",
        "scuola": "Scuola",
        "dottore": "Dottore",
        "compleanni": "Compleanni",
    },
    "de": {
        "famiglia": "Familie",
        "scuola": "Schule",
        "dottore": "Arzt",
        "compleanni": "Geburtstage",
    },
    "en": {
        "famiglia": "Family",
        "scuola": "School",
        "dottore": "Doctor",
        "compleanni": "Birthdays",
    },
}

DEFAULT_CATEGORIES: Final[list[dict[str, str]]] = [
    {"id": "famiglia", "name": "Famiglia", "color": "#3B82F6"},
    {"id": "scuola", "name": "Scuola", "color": "#10B981"},
    {"id": "dottore", "name": "Dottore", "color": "#EF4444"},
    {"id": "compleanni", "name": "Compleanni", "color": "#F59E0B"},
]


def category_id_for(name: str, taken: set[str]) -> str:
    """A readable id for a new category, from its name: "Sport" becomes "sport", so its calendar is
    calendar.family_hub_sport. A number is added when the id is taken; a name with no letters
    gets a random id."""
    text = unicodedata.normalize("NFKD", name.lower()).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^a-z0-9]+", "_", text).strip("_")[:24] or uuid.uuid4().hex[:8]
    candidate, number = base, 2
    while candidate in taken:
        candidate = f"{base}_{number}"
        number += 1
    return candidate


def language_from_home(language: str | None) -> str:
    """The family's language as a default: Home Assistant's language when the app has it, else
    English. Never a fixed language."""
    code = str(language or "").split("-")[0].lower()
    return code if code in LANGUAGES else "en"


def first_weekday_for(language: str, country: str | None) -> str:
    """Monday, or Sunday for the countries and languages that start the week on Sunday."""
    if language == "en" and str(country or "").upper() in {"US", "CA", "JP", "IL"}:
        return "sunday"
    return "monday"


def default_categories(language: str) -> list[dict[str, str]]:
    """The default categories, named in the family's language (English if unknown)."""
    names = CATEGORY_NAMES.get(language, CATEGORY_NAMES["en"])
    return [{**category, "name": names[category["id"]]} for category in DEFAULT_CATEGORIES]


# Action (service) names and field names.
SERVICE_ADD_EVENT: Final = "add_event"
SERVICE_UPDATE_EVENT: Final = "update_event"
SERVICE_DELETE_EVENT: Final = "delete_event"
SERVICE_MOVE_EVENT: Final = "move_event"
SERVICE_SNOOZE_REMINDER: Final = "snooze_reminder"
SERVICE_STOP_REMINDER: Final = "stop_reminder"

ATTR_ENTRY_ID: Final = "entry_id"
ATTR_CATEGORY: Final = "category"
ATTR_UID: Final = "uid"
ATTR_SUMMARY: Final = "summary"
ATTR_START: Final = "start"
ATTR_END: Final = "end"
ATTR_DESCRIPTION: Final = "description"
ATTR_LOCATION: Final = "location"
ATTR_PERSONS: Final = "persons"
ATTR_REMINDER_OFFSETS: Final = "reminder_offsets"
ATTR_MINUTES: Final = "minutes"
ATTR_SHIFT_ID: Final = "shift_id"
# Entry options: shift models, a dict of person id -> list of models.
OPT_SHIFTS: Final = "shifts"

# Person fields for reminders (all optional).
CONF_PHONE_NOTIFY: Final = "phone_notify"
CONF_SPEAKER: Final = "speaker"
CONF_QUIET_START: Final = "quiet_start"
CONF_QUIET_END: Final = "quiet_end"
CONF_ALEXA_NOTIFY: Final = "alexa_notify"
# Optional link to a Home Assistant user: the tablet add-on uses it to apply the person's role.
CONF_HA_USER: Final = "ha_user_id"
# Per-person notification settings (the "Avvisi" page): channels that reach the person, the
# announce volume on Echo speakers (0-100, optional), and the services the person may use.
CONF_ALEXA_VOLUME: Final = "alexa_volume"
# How a reminder sounds on the phone: normal, important (time sensitive, the default) or
# critical (through Full immersion / Do not disturb; iPhone needs the critical alerts permission).
CONF_PHONE_SOUND: Final = "phone_sound"
PHONE_SOUNDS: Final[list[str]] = ["normal", "important", "critical"]
DEFAULT_PHONE_SOUND: Final = "important"
CONF_CHANNELS: Final = "channels"
PERSON_CHANNELS: Final[list[str]] = ["phone", "alexa", "tablet"]
# alexa_notify is one Echo service, or ALEXA_ALL for every Echo that Home Assistant knows.
ALEXA_ALL: Final = "all"
PHONE_SERVICE_PREFIX: Final = "mobile_app_"
ALEXA_PLATFORM: Final = "alexa_media"
# An announcement at a chosen volume: the volume is set, then the speakers are given up to
# ECHO_WAIT_MAX_SECONDS to reach it (and ECHO_WAIT_MIN_SECONDS in all) before the announcement.
ECHO_WAIT_MAX_SECONDS: Final = 5
ECHO_WAIT_MIN_SECONDS: Final = 2
# The old volume comes back when the message has been spoken: this many seconds, plus this per
# character of the message.
ECHO_RESTORE_BASE_SECONDS: Final = 20
ECHO_RESTORE_PER_CHAR_SECONDS: Final = 0.1
# Where an Echo goes back to when its old volume was not known.
ECHO_FALLBACK_VOLUME: Final = 0.3
# Media players of the Alexa platform that are not speakers: the multiroom group, the Fire TV
# and the Alexa app on this device. Matched on their entity id and name, lower case, no underscores.
ECHO_NOT_SPEAKER_NAMES: Final = ("everywhere", "ovunque", "fire tv", "firetv", "this device")
CONF_ALL_DAY_REMINDER: Final = "all_day_reminder"
ATTR_ALL_DAY_REMINDER: Final = "all_day_reminder"
# How one event's reminders go out, instead of its persons' own settings: the channels
# ("phone", "alexa", "tablet"), the Echo ("all" or a media_player) and its volume.
ATTR_CHANNELS: Final = "channels"
ATTR_ALEXA_TARGET: Final = "alexa_target"
ATTR_ALEXA_VOLUME: Final = "alexa_volume"
ATTR_PHONE_SOUND: Final = "phone_sound"
EVENT_CHANNELS: Final[list[str]] = ["phone", "alexa", "tablet"]

# Entry options: reminder settings, read by reminders.py.
OPT_REMINDERS: Final = "reminders"
# phone: notify.<service>; speaker: Alexa announce or tts.speak; tablet: persistent
# notification; popup: browser_mod.popup (only if browser_mod is installed).
CHANNELS: Final[list[str]] = ["phone", "speaker", "tablet", "popup"]
DEFAULT_REMINDERS: Final[dict[str, Any]] = {
    "offsets": [30, 10],  # minutes before the start
    "channels": ["phone", "speaker", "tablet"],
    "quiet_start": "22:00",  # no reminders from quiet_start until quiet_end (family default)
    "quiet_end": "07:00",
    "snooze_minutes": 10,  # default for snooze_reminder
    "tts_entity": None,  # tts.* entity used for spoken reminders
    "morning_summary": "07:00",  # the time of the morning summary
    "evening_summary": "20:00",
    "morning_summary_on": True,  # the switch: off keeps the time, sends nothing
    "evening_summary_on": True,
    # Where the summaries go: "phone", "alexa" (the person's Echo) and "tablet". Off by default
    # for Alexa.
    "summary_channels": ["phone", "tablet"],
    "all_day_reminder": "19:00",  # day before an all-day event, local time
}
SUMMARY_CHANNELS: Final = ("phone", "alexa", "tablet")

# Bus events for the tablet add-on: a reminder popup to show, and one to close.
EVENT_REMINDER: Final = "family_hub_reminder"
EVENT_REMINDER_CLOSED: Final = "family_hub_reminder_closed"

# Phone notification buttons send FH_<CMD>[_<minutes>]_<uid> back as a mobile_app event.
ACTION_EVENT: Final = "mobile_app_notification_action"
ACTION_PREFIX: Final = "FH_"
