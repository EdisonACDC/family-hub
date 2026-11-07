"""Weather for the morning summary: today's condition, temperature and high/low.

The forecast comes from the weather entity the guide chose (weather.* in Home Assistant). A
missing forecast leaves out the high and low, never the whole line.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

LOGGER = logging.getLogger(__name__)

# Home Assistant's condition names, in the family's languages.
CONDITION_WORDS: dict[str, dict[str, str]] = {
    "it": {
        "clear-night": "sereno",
        "sunny": "sereno",
        "cloudy": "nuvoloso",
        "partlycloudy": "parzialmente nuvoloso",
        "rainy": "pioggia",
        "pouring": "pioggia intensa",
        "snowy": "neve",
        "snowy-rainy": "neve e pioggia",
        "fog": "nebbia",
        "hail": "grandine",
        "lightning": "temporale",
        "lightning-rainy": "temporale",
        "windy": "ventoso",
        "windy-variant": "ventoso",
        "exceptional": "eccezionale",
    },
    "de": {
        "clear-night": "klar",
        "sunny": "sonnig",
        "cloudy": "bewölkt",
        "partlycloudy": "teilweise bewölkt",
        "rainy": "Regen",
        "pouring": "starker Regen",
        "snowy": "Schnee",
        "snowy-rainy": "Schneeregen",
        "fog": "Nebel",
        "hail": "Hagel",
        "lightning": "Gewitter",
        "lightning-rainy": "Gewitter",
        "windy": "windig",
        "windy-variant": "windig",
        "exceptional": "außergewöhnlich",
    },
    "en": {
        "clear-night": "clear",
        "sunny": "sunny",
        "cloudy": "cloudy",
        "partlycloudy": "partly cloudy",
        "rainy": "rain",
        "pouring": "heavy rain",
        "snowy": "snow",
        "snowy-rainy": "sleet",
        "fog": "fog",
        "hail": "hail",
        "lightning": "thunderstorm",
        "lightning-rainy": "thunderstorm",
        "windy": "windy",
        "windy-variant": "windy",
        "exceptional": "exceptional",
    },
}
MAX_MIN = {"it": ("max", "min"), "de": ("max", "min"), "en": ("high", "low")}


def condition_word(condition: str, language: str) -> str:
    words = CONDITION_WORDS.get(language, CONDITION_WORDS["en"])
    return words.get(condition, condition)


def _num(value: Any) -> str | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(round(value))
    return None


async def summary_line(hass: HomeAssistant, entity_id: str, language: str) -> str | None:
    """ "5°, nuvoloso, max 8°, min 2°" for the morning summary, or None if the entity is unknown."""
    state = hass.states.get(entity_id)
    if state is None:
        return None
    unit = str(state.attributes.get("temperature_unit", "°C"))
    parts: list[str] = []
    now = _num(state.attributes.get("temperature"))
    if now is not None:
        parts.append(f"{now}{unit}")
    if state.state not in ("unknown", "unavailable"):
        parts.append(condition_word(state.state, language))
    high = low = None
    try:
        result: Any = await hass.services.async_call(
            "weather",
            "get_forecasts",
            {"entity_id": entity_id, "type": "daily"},
            blocking=True,
            return_response=True,
        )
        today = (result or {}).get(entity_id, {}).get("forecast", [])
        if today:
            high = _num(today[0].get("temperature"))
            low = _num(today[0].get("templow"))
    except Exception as err:  # the forecast is optional
        LOGGER.debug("No forecast from %s: %s", entity_id, err)
    max_word, min_word = MAX_MIN.get(language, MAX_MIN["en"])
    if high is not None:
        parts.append(f"{max_word} {high}{unit}")
    if low is not None:
        parts.append(f"{min_word} {low}{unit}")
    return ", ".join(parts) or None
