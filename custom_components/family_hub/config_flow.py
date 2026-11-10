"""Config flow and options flow for Family Hub."""

from __future__ import annotations

import re
import uuid
from typing import Any

import probatio as vol  # Home Assistant's schema library (voluptuous successor).
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector

from .const import (
    CHANNELS,
    CONF_ALEXA_NOTIFY,
    CONF_ALL_DAY_REMINDER,
    CONF_FAMILY_NAME,
    CONF_FIRST_WEEKDAY,
    CONF_HA_USER,
    CONF_LANGUAGE,
    CONF_PHONE_NOTIFY,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_SPEAKER,
    DEFAULT_REMINDERS,
    DOMAIN,
    LANGUAGE_NAMES,
    LANGUAGES,
    OPT_CATEGORIES,
    OPT_PERSONS,
    OPT_REMINDERS,
    ROLES,
    WEEKDAYS,
    category_id_for,
    default_categories,
    first_weekday_for,
    language_from_home,
)
from .reminders import parse_hhmm

CONF_NAME = "name"
CONF_COLOR = "color"
CONF_ROLE = "role"
CONF_PERSON = "person"
CONF_CATEGORY = "category"
# Reminder settings fields (the options stored are in const.DEFAULT_REMINDERS).
CONF_OFFSETS = "offsets"
CONF_CHANNELS = "channels"
CONF_SNOOZE = "snooze_minutes"
CONF_TTS = "tts_entity"
CONF_MORNING = "morning_summary"
CONF_EVENING = "evening_summary"

COLOR_VALIDATOR = vol.Match(r"^#[0-9A-Fa-f]{6}$")


def _select(options: list[str], translation_key: str | None = None) -> selector.SelectSelector:
    config = selector.SelectSelectorConfig(
        options=options,
        mode=selector.SelectSelectorMode.DROPDOWN,
    )
    if translation_key is not None:
        config["translation_key"] = translation_key
    return selector.SelectSelector(config)


def _language_select() -> selector.SelectSelector:
    """The languages with their own names (Italiano, Deutsch, English), not the codes."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(value=code, label=LANGUAGE_NAMES[code])
                for code in LANGUAGES
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _parse_offsets(text: str) -> list[int] | None:
    """Turn "30, 10" into [30, 10]. Returns None if a value is not a whole number >= 0."""
    parts = [part for part in re.split(r"[,\s]+", text.strip()) if part]
    try:
        offsets = [int(part) for part in parts]
    except ValueError:
        return None
    return None if any(offset < 0 for offset in offsets) else offsets


def _bad_time(value: Any) -> bool:
    """True if a value is set but is not HH:MM. Empty means not set, which is allowed."""
    try:
        parse_hhmm(value or None)
    except ValueError:
        return True
    return False


def user_schema(hass: Any) -> vol.Schema:
    """The first form, with the language and the first weekday of Home Assistant as defaults."""
    language = language_from_home(hass.config.language)
    weekday = first_weekday_for(language, hass.config.country)
    return vol.Schema(
        {
            vol.Required(CONF_FAMILY_NAME): vol.All(str, vol.Length(max=60)),
            vol.Required(CONF_LANGUAGE, default=language): _language_select(),
            vol.Required(CONF_FIRST_WEEKDAY, default=weekday): _select(WEEKDAYS, "weekday"),
        }
    )


PERSON_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): vol.All(str, vol.Length(max=60)),
        vol.Required(CONF_COLOR, default="#3B82F6"): vol.All(str, COLOR_VALIDATOR),
        vol.Required(CONF_ROLE, default="adult"): _select(ROLES, "role"),
        # Optional reminder targets. phone_notify is the notify service name, e.g. mobile_app_pixel.
        vol.Optional(CONF_PHONE_NOTIFY): cv.string,
        vol.Optional(CONF_SPEAKER): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="media_player")
        ),
        vol.Optional(CONF_ALEXA_NOTIFY): cv.string,
        vol.Optional(CONF_HA_USER): cv.string,
        vol.Optional(CONF_QUIET_START): cv.string,
        vol.Optional(CONF_QUIET_END): cv.string,
        vol.Optional(CONF_ALL_DAY_REMINDER): cv.string,
    }
)

CATEGORY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): vol.All(str, vol.Length(max=60)),
        vol.Required(CONF_COLOR, default="#3B82F6"): vol.All(str, COLOR_VALIDATOR),
    }
)


def _reminders_schema(current: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_OFFSETS, default=", ".join(str(m) for m in current["offsets"])
            ): cv.string,
            vol.Required(CONF_CHANNELS, default=list(current["channels"])): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=CHANNELS,
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            vol.Required(CONF_QUIET_START, default=current["quiet_start"] or ""): cv.string,
            vol.Required(CONF_QUIET_END, default=current["quiet_end"] or ""): cv.string,
            vol.Required(CONF_SNOOZE, default=current["snooze_minutes"]): vol.All(
                cv.positive_int, vol.Range(min=1, max=1440)
            ),
            vol.Optional(CONF_TTS): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="tts")
            ),
            vol.Optional(CONF_MORNING, default=current["morning_summary"] or ""): cv.string,
            vol.Optional(CONF_EVENING, default=current["evening_summary"] or ""): cv.string,
            vol.Optional(
                CONF_ALL_DAY_REMINDER, default=current["all_day_reminder"] or ""
            ): cv.string,
        }
    )


class FamilyHubConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create the single Family Hub configuration."""

    VERSION = 2

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the family name, language and first weekday."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_FAMILY_NAME].strip()
            if not name:
                errors[CONF_FAMILY_NAME] = "empty_name"
            else:
                return self.async_create_entry(
                    title=name,
                    data={},
                    options={
                        CONF_FAMILY_NAME: name,
                        CONF_LANGUAGE: user_input[CONF_LANGUAGE],
                        CONF_FIRST_WEEKDAY: user_input[CONF_FIRST_WEEKDAY],
                        OPT_PERSONS: [],
                        OPT_CATEGORIES: default_categories(user_input[CONF_LANGUAGE]),
                        OPT_REMINDERS: dict(DEFAULT_REMINDERS),
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=user_schema(self.hass), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> FamilyHubOptionsFlow:
        """Return the options flow."""
        return FamilyHubOptionsFlow()


class FamilyHubOptionsFlow(OptionsFlow):
    """Add and remove persons and categories; set reminder defaults."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "add_person",
                "remove_person",
                "add_category",
                "remove_category",
                "reminders",
            ],
        )

    def _options(self) -> dict[str, Any]:
        return dict(self.config_entry.options)

    async def async_step_add_person(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a family member."""
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            if not name:
                errors[CONF_NAME] = "empty_name"
            for key in (CONF_QUIET_START, CONF_QUIET_END, CONF_ALL_DAY_REMINDER):
                if _bad_time(user_input.get(key)):
                    errors[key] = "invalid_time"
            if not errors:
                person: dict[str, Any] = {
                    "id": uuid.uuid4().hex[:8],
                    "name": name,
                    "color": user_input[CONF_COLOR],
                    "role": user_input[CONF_ROLE],
                }
                for key in (
                    CONF_PHONE_NOTIFY,
                    CONF_SPEAKER,
                    CONF_ALEXA_NOTIFY,
                    CONF_HA_USER,
                    CONF_QUIET_START,
                    CONF_QUIET_END,
                    CONF_ALL_DAY_REMINDER,
                ):
                    value = (user_input.get(key) or "").strip()
                    if value:
                        person[key] = value
                options = self._options()
                options[OPT_PERSONS] = [*options.get(OPT_PERSONS, []), person]
                return self.async_create_entry(title="", data=options)
        return self.async_show_form(step_id="add_person", data_schema=PERSON_SCHEMA, errors=errors)

    async def async_step_remove_person(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove a family member. Their past events keep the old id."""
        persons = self._options().get(OPT_PERSONS, [])
        if not persons:
            return self.async_abort(reason="no_persons")
        if user_input is not None:
            options = self._options()
            options[OPT_PERSONS] = [p for p in persons if p["id"] != user_input[CONF_PERSON]]
            return self.async_create_entry(title="", data=options)
        schema = vol.Schema(
            {
                vol.Required(CONF_PERSON): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=p["id"], label=p["name"])
                            for p in persons
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="remove_person", data_schema=schema)

    async def async_step_add_category(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a category, which becomes a calendar."""
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            if not name:
                errors[CONF_NAME] = "empty_name"
            else:
                options = self._options()
                taken = {str(c.get("id")) for c in options.get(OPT_CATEGORIES, [])}
                options[OPT_CATEGORIES] = [
                    *options.get(OPT_CATEGORIES, []),
                    {
                        "id": category_id_for(name, taken),
                        "name": name,
                        "color": user_input[CONF_COLOR],
                    },
                ]
                return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="add_category", data_schema=CATEGORY_SCHEMA, errors=errors
        )

    async def async_step_remove_category(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove a category. Refused while it still has events."""
        categories = self._options().get(OPT_CATEGORIES, [])
        errors: dict[str, str] = {}
        if user_input is not None:
            category_id = user_input[CONF_CATEGORY]
            events = self.config_entry.runtime_data.store.events.values()
            if any(event["category"] == category_id for event in events):
                errors[CONF_CATEGORY] = "category_in_use"
            else:
                options = self._options()
                options[OPT_CATEGORIES] = [c for c in categories if c["id"] != category_id]
                return self.async_create_entry(title="", data=options)
        schema = vol.Schema(
            {
                vol.Required(CONF_CATEGORY): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=c["id"], label=c["name"])
                            for c in categories
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="remove_category", data_schema=schema, errors=errors)

    async def async_step_reminders(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Family-wide reminder defaults: offsets, channels, quiet hours, summaries."""
        current = {**DEFAULT_REMINDERS, **self._options().get(OPT_REMINDERS, {})}
        errors: dict[str, str] = {}
        if user_input is not None:
            offsets = _parse_offsets(user_input[CONF_OFFSETS])
            if offsets is None:
                errors[CONF_OFFSETS] = "invalid_offsets"
            for key in (
                CONF_QUIET_START,
                CONF_QUIET_END,
                CONF_MORNING,
                CONF_EVENING,
                CONF_ALL_DAY_REMINDER,
            ):
                if _bad_time(user_input.get(key)):
                    errors[key] = "invalid_time"
            if not errors and offsets is not None:
                options = self._options()
                options[OPT_REMINDERS] = {
                    "offsets": offsets,
                    "channels": list(user_input[CONF_CHANNELS]),
                    "quiet_start": (user_input[CONF_QUIET_START] or "").strip(),
                    "quiet_end": (user_input[CONF_QUIET_END] or "").strip(),
                    "snooze_minutes": user_input[CONF_SNOOZE],
                    "tts_entity": user_input.get(CONF_TTS) or None,
                    "morning_summary": (user_input.get(CONF_MORNING) or "").strip() or None,
                    "evening_summary": (user_input.get(CONF_EVENING) or "").strip() or None,
                    "all_day_reminder": (user_input.get(CONF_ALL_DAY_REMINDER) or "").strip()
                    or None,
                }
                return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="reminders", data_schema=_reminders_schema(current), errors=errors
        )
