"""Weather: the weather entity the guide chooses, and today's line in the morning summary."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant, ServiceResponse, SupportsResponse

from custom_components.family_hub.api import ConfigError, clean_config
from custom_components.family_hub.weather import condition_word, summary_line

WEATHER = "weather.home"


def _config(sources: dict[str, Any]) -> dict[str, Any]:
    return {
        "family": {
            "family_name": "Esempio",
            "language": "it",
            "first_weekday": "monday",
            "time_format": "24h",
        },
        "screen": {"theme": "auto"},
        "persons": [],
        "categories": [{"name": "Famiglia", "color": "#3B82F6"}],
        "reminders": {},
        "sources": sources,
    }


def _known(entity_id: str) -> bool:
    return entity_id in {WEATHER, "weather.other", "calendar.rifiuti"}


def test_one_weather_entity_is_stored() -> None:
    options = clean_config(_config({"weather": [WEATHER]}), {}, None, _known)
    assert options["sources"]["weather"] == [WEATHER]


@pytest.mark.parametrize(
    "sources",
    [
        {"weather": ["calendar.rifiuti"]},  # wrong domain
        {"weather": ["weather.missing"]},  # does not exist
        {"weather": [WEATHER, "weather.other"]},  # only one
    ],
)
def test_bad_weather_choice_is_refused(sources: dict[str, Any]) -> None:
    with pytest.raises(ConfigError):
        clean_config(_config(sources), {}, None, _known)


def test_condition_words_follow_the_language() -> None:
    assert condition_word("cloudy", "it") == "nuvoloso"
    assert condition_word("cloudy", "de") == "bewölkt"
    assert condition_word("cloudy", "en") == "cloudy"
    assert condition_word("unknown-key", "it") == "unknown-key"


async def test_summary_line_has_now_condition_and_high_low(hass: HomeAssistant) -> None:
    hass.states.async_set(WEATHER, "cloudy", {"temperature": 5, "temperature_unit": "°C"})

    async def forecasts(call: Any) -> ServiceResponse:
        return {WEATHER: {"forecast": [{"temperature": 8, "templow": 2}]}}

    hass.services.async_register(
        "weather", "get_forecasts", forecasts, supports_response=SupportsResponse.ONLY
    )
    assert await summary_line(hass, WEATHER, "it") == "5°C, nuvoloso, max 8°C, min 2°C"


async def test_summary_line_without_forecast_keeps_the_rest(hass: HomeAssistant) -> None:
    hass.states.async_set(WEATHER, "rainy", {"temperature": 3, "temperature_unit": "°C"})
    assert await summary_line(hass, WEATHER, "en") == "3°C, rain"


async def test_unknown_weather_entity_gives_no_line(hass: HomeAssistant) -> None:
    assert await summary_line(hass, "weather.nessuno", "it") is None
