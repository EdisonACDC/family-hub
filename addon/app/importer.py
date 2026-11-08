"""Copy events from an old Home Assistant calendar into a Family Hub category, once.

The import never duplicates: an event is skipped when the category already has an event with
the same title, start and end. So running the import again only adds what is new.
"""

from __future__ import annotations

from typing import Any

PREVIEW_COUNT = 10
# The events of the last days are copied too, so that recent history is not lost.
PAST_DAYS = 30
# How far ahead events are copied.
FUTURE_YEARS = 3


def key_of(event: dict[str, Any]) -> tuple[str, str, str]:
    """What makes two events the same: title, start and end (to the minute)."""
    return (
        str(event.get("summary", "")).strip(),
        str(event.get("start", ""))[:16],
        str(event.get("end", ""))[:16],
    )


def plan(
    source: list[dict[str, Any]], existing: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    """The events to copy, and how many were skipped because they are already there.

    An event without a title or a start is skipped. Repeats inside the source count as
    skipped too: only the first is copied.
    """
    seen = {key_of(event) for event in existing}
    skipped = 0
    to_copy: list[dict[str, Any]] = []
    for event in source:
        key = key_of(event)
        if not key[0] or not key[1]:
            continue
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        to_copy.append(event)
    return to_copy, skipped


def service_data(event: dict[str, Any], category_id: str, persons: list[str]) -> dict[str, Any]:
    """The family_hub.add_event data for one copied event."""
    data: dict[str, Any] = {
        "category": category_id,
        "summary": str(event["summary"]).strip()[:255],
        "start": str(event["start"]),
        "end": str(event.get("end") or event["start"]),
        "persons": persons,
    }
    location = str(event.get("location") or "").strip()
    if location:
        data["location"] = location[:255]
    return data
