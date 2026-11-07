"""Shift models ("turni") per person.

A model has a stable id, a name, a start and an end time (an end before the start means the
shift runs past midnight) and a category, which is a calendar category. Events created from a
model keep its id in ``shift_id``, so a change of times can reach the events already entered.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from .models import FamilyHubConfigEntry

TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ShiftError(ValueError):
    """A shift model sent by the guide or the shift editor is not valid."""


def clean_shifts(raw: Any, categories: set[str]) -> list[dict[str, str]]:
    """Validate the models of one person. Names are unique per person (case ignored)."""
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise ShiftError("shifts: must be a list of objects")
    cleaned: list[dict[str, str]] = []
    names: set[str] = set()
    for index, item in enumerate(raw):
        field = f"shifts[{index}]"
        name = str(item.get("name", "")).strip()
        if not name or len(name) > 60:
            raise ShiftError(f"{field}.name: required, at most 60 characters")
        if name.lower() in names:
            raise ShiftError(f"{field}.name: '{name}' is already used")
        names.add(name.lower())
        start = str(item.get("start", ""))
        end = str(item.get("end", ""))
        for label, value in (("start", start), ("end", end)):
            if not TIME_PATTERN.match(value):
                raise ShiftError(f"{field}.{label}: use HH:MM")
        if start == end:
            raise ShiftError(f"{field}: start and end must differ")
        category = str(item.get("category", ""))
        if category not in categories:
            raise ShiftError(f"{field}.category: unknown category")
        shift_id = str(item.get("id") or uuid.uuid4().hex[:8])
        cleaned.append(
            {"id": shift_id, "name": name, "start": start, "end": end, "category": category}
        )
    if len({s["id"] for s in cleaned}) != len(cleaned):
        raise ShiftError("shifts: duplicate id")
    return cleaned


def crosses_midnight(shift: dict[str, str]) -> bool:
    return shift["end"] < shift["start"]


async def apply_to_future(
    entry: FamilyHubConfigEntry, changes: dict[str, dict[str, str]], person: str
) -> int:
    """Update the events of changed models from tomorrow on. Past and today's events stay as
    they are. Returns how many events changed."""
    tz = dt_util.get_default_time_zone()
    today = datetime.now(tz).date()
    store = entry.runtime_data.store
    updated = 0
    for record in store.events.values():
        shift = changes.get(record.get("shift_id", ""))
        if shift is None or person not in record.get("persons", []):
            continue
        day = date.fromisoformat(record["start"][:10])
        if day <= today:
            continue
        end_day = day + timedelta(days=1) if crosses_midnight(shift) else day
        record["start"] = datetime.combine(
            day, time.fromisoformat(shift["start"]), tzinfo=tz
        ).isoformat()
        record["end"] = datetime.combine(
            end_day, time.fromisoformat(shift["end"]), tzinfo=tz
        ).isoformat()
        record["summary"] = shift["name"]
        record["category"] = shift["category"]
        record["all_day"] = False
        updated += 1
    if updated:
        await store.async_save()
        for calendar in entry.runtime_data.calendars.values():
            calendar.async_write_ha_state()
    return updated
