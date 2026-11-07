"""Diagnostics for Family Hub. Personal names and event text are not included."""

from __future__ import annotations

from collections import Counter
from typing import Any

from homeassistant.core import HomeAssistant

from .const import OPT_CATEGORIES, OPT_PERSONS
from .models import FamilyHubConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FamilyHubConfigEntry
) -> dict[str, Any]:
    """Return counts and ids only."""
    events = entry.runtime_data.store.events.values()
    per_category = Counter(event["category"] for event in events)
    categories = entry.options.get(OPT_CATEGORIES, [])
    persons = entry.options.get(OPT_PERSONS, [])
    return {
        "language": entry.options.get("language"),
        "first_weekday": entry.options.get("first_weekday"),
        "person_count": len(persons),
        "person_roles": dict(Counter(p.get("role") for p in persons)),
        "categories": [{"id": c["id"], "events": per_category.get(c["id"], 0)} for c in categories],
        "event_count": len(events),
    }
