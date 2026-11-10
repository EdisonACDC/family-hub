"""Rule B: every text comes from the table of the family's language (it, de, en), and the defaults
follow Home Assistant's language and country. Nothing is fixed to Italian."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.family_hub import external
from custom_components.family_hub.const import (
    CONF_FAMILY_NAME,
    CONF_FIRST_WEEKDAY,
    CONF_LANGUAGE,
    DOMAIN,
    OPT_CATEGORIES,
    OPT_PERSONS,
    OPT_REMINDERS,
    first_weekday_for,
    language_from_home,
)
from custom_components.family_hub.notifier import sound_data, texts_for


def test_home_assistant_language_is_used_when_the_app_has_it() -> None:
    assert language_from_home("de") == "de"
    assert language_from_home("de-AT") == "de"
    assert language_from_home("it-CH") == "it"
    assert language_from_home("EN") == "en"


def test_any_other_language_is_english() -> None:
    assert language_from_home("fr") == "en"
    assert language_from_home("") == "en"
    assert language_from_home(None) == "en"


def test_the_week_starts_on_sunday_only_where_it_does() -> None:
    assert first_weekday_for("en", "US") == "sunday"
    assert first_weekday_for("en", "GB") == "monday"
    assert first_weekday_for("it", "US") == "monday"
    assert first_weekday_for("de", None) == "monday"


def _defaults(schema: Any) -> dict[str, Any]:
    """The default of each field that has one (a field without a default has none to call)."""
    found: dict[str, Any] = {}
    for key in schema:
        try:
            found[str(key)] = key.default()
        except TypeError:
            continue
    return found


async def test_the_guide_defaults_follow_home_assistant(hass: HomeAssistant) -> None:
    hass.config.language = "de"
    hass.config.country = "AT"
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    defaults = _defaults(result["data_schema"].schema)
    assert defaults[CONF_LANGUAGE] == "de"
    assert defaults[CONF_FIRST_WEEKDAY] == "monday"


async def test_the_guide_defaults_to_english_for_an_unknown_language(hass: HomeAssistant) -> None:
    hass.config.language = "fr"
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    defaults = _defaults(result["data_schema"].schema)
    assert defaults[CONF_LANGUAGE] == "en"


@pytest.mark.parametrize("language", ["it", "de", "en"])
def test_every_language_has_the_same_texts(language: str) -> None:
    texts = texts_for(language)
    assert set(texts) == set(texts_for("en")), language
    assert all(value.strip() for value in texts.values()), language
    words = external.SUMMARY_TEXTS[language]
    assert set(words) == set(external.SUMMARY_TEXTS["en"]), language


@pytest.mark.parametrize(
    ("language", "channel", "urgent", "test_word"),
    [
        ("it", "Promemoria Family Hub", "Promemoria Family Hub urgenti", "Prova"),
        ("de", "Erinnerungen Family Hub", "Dringende Erinnerungen Family Hub", "Test"),
        ("en", "Family Hub reminders", "Urgent Family Hub reminders", "Test"),
    ],
)
def test_the_phone_channel_and_test_text_follow_the_language(
    language: str, channel: str, urgent: str, test_word: str
) -> None:
    assert sound_data("important", "android", language)["channel"] == channel
    assert sound_data("critical", "android", language)["channel"] == urgent
    assert texts_for(language)["test"].startswith(test_word)


def test_english_and_german_texts_have_no_italian_words() -> None:
    for language in ("de", "en"):
        everything = " ".join(
            [*texts_for(language).values(), *external.SUMMARY_TEXTS[language].values()]
        )
        for word in ("Promemoria", "Rifiuti", "Vacanze", "Prova", "Festività"):
            assert word not in everything, (language, word)


_SUMMARY_CASES: list[tuple[str, str, str, str]] = [
    # language, a rubbish title, the words it reads as, a holiday name
    ("it", "Umido", "Rifiuti: Organico", "Vacanze scuola"),
    ("de", "Bioabfall", "Müll: Biomüll", "Schulferien"),
    ("en", "Food waste", "Waste: Food waste", "School holidays"),
]


@pytest.mark.parametrize(("language", "title", "rubbish", "holiday"), _SUMMARY_CASES)
async def test_the_summary_is_in_the_family_language(
    hass: HomeAssistant,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
    language: str,
    title: str,
    rubbish: str,
    holiday: str,
) -> None:
    freezer.move_to(datetime(2026, 11, 10, 8, tzinfo=dt_util.get_default_time_zone()))
    days = {"calendar.rifiuti": [title], "calendar.vacanze": ["Holidays", "Other name"]}

    async def names_on(self: Any, entity_id: str, day: Any) -> list[str]:
        return days.get(entity_id, []) if day.isoformat() == "2026-11-10" else []

    monkeypatch.setattr(external.ExternalManager, "_ha_names_on", names_on)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: language, CONF_FIRST_WEEKDAY: "monday"},
        options={
            CONF_LANGUAGE: language,
            OPT_PERSONS: [],
            OPT_CATEGORIES: [{"id": "famiglia", "name": "Famiglia", "color": "#3B82F6"}],
            OPT_REMINDERS: {"summary_channels": ["tablet"]},
            "sources": {
                "calendar_styles": {
                    "calendar.rifiuti": {"type": "rifiuti", "color": "#8B5A2B", "persons": []},
                    "calendar.vacanze": {
                        "type": "vacanze_scuola",
                        "color": "#0EA5E9",
                        "persons": [],
                    },
                }
            },
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    tablet = async_mock_service(hass, "persistent_notification", "create")
    await entry.runtime_data.reminders.async_send_summary("morning")
    (family,) = tablet
    message = family.data["message"]
    assert rubbish in message
    assert message.count(holiday) == 1
