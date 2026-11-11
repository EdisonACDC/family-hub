"""Rubbish pickups made by hand, for a family with no calendar file.

The family gives, per rubbish type, a weekday, a frequency and the date of the first pickup:
every week, every 2 weeks, every 4 weeks, or every month on the same day (in a shorter
month, the last day). Single extra dates, skipped dates and moved pickups change that series.

The pickups are written out as calendar text (ICS). They are then read like a downloaded calendar:
shown, classified by their titles, reminded and summarised. Nothing here depends on a name of the
family or the home: the types come from the family's own list.
"""

from __future__ import annotations

import calendar as month_calendar
from datetime import date, datetime, timedelta
from typing import Any

SOURCE_ID = "manualwaste"  # no "_" or "." (reminder ids are split on "_")
FREQUENCIES: dict[str, int] = {"weekly": 7, "biweekly": 14, "four_weeks": 28, "monthly": 0}
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
# How far past the last given date the pickups are written out.
HORIZON_DAYS = 730
MAX_EXTRA = 200
MAX_SKIP = 500
MAX_MOVES = 200


class ManualWasteError(ValueError):
    """A schedule that cannot be used. ``code`` says why, for the page to explain."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def empty() -> dict[str, list[dict[str, str]]]:
    """No pickups made by hand."""
    return {"rules": [], "extra": [], "skip": [], "moves": []}


def _day(value: Any) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as err:
        raise ManualWasteError("invalid_date") from err


def normalize(raw: Any, type_ids: set[str]) -> dict[str, list[dict[str, str]]]:
    """Check a schedule from the page and return it in the stored form. Raises ManualWasteError."""
    if not isinstance(raw, dict):
        raise ManualWasteError("invalid")
    rules: list[dict[str, str]] = []
    seen_types: set[str] = set()
    for item in raw.get("rules") or []:
        kind = str(item.get("type") or "")
        if kind not in type_ids:
            raise ManualWasteError("unknown_type")
        if kind in seen_types:
            raise ManualWasteError("type_twice")
        seen_types.add(kind)
        frequency = str(item.get("frequency") or "")
        if frequency not in FREQUENCIES:
            raise ManualWasteError("invalid_frequency")
        first = _day(item.get("first"))
        weekday = WEEKDAYS[first.weekday()]
        given = str(item.get("weekday") or "")
        if frequency != "monthly" and given != weekday:
            # The first date must fall on the weekday the family chose.
            raise ManualWasteError("weekday_mismatch")
        rules.append(
            {"type": kind, "frequency": frequency, "weekday": weekday, "first": first.isoformat()}
        )
    extra = _dated(raw.get("extra") or [], type_ids, "type", MAX_EXTRA)
    skip = _dated(raw.get("skip") or [], type_ids | {""}, "type", MAX_SKIP)
    moves: list[dict[str, str]] = []
    for item in (raw.get("moves") or [])[:MAX_MOVES]:
        kind = str(item.get("type") or "")
        if kind not in type_ids:
            raise ManualWasteError("unknown_type")
        source, target = _day(item.get("from")), _day(item.get("to"))
        moves.append({"type": kind, "from": source.isoformat(), "to": target.isoformat()})
    if len(raw.get("moves") or []) > MAX_MOVES:
        raise ManualWasteError("too_many")
    schedule = {"rules": rules, "extra": extra, "skip": skip, "moves": moves}
    # A pickup can only be moved if it is there to move.
    base = {(kind, day) for kind, day in _series_of(schedule)}
    for move in moves:
        if (move["type"], date.fromisoformat(move["from"])) not in base:
            raise ManualWasteError("move_not_found")
    return schedule


def _dated(items: Any, type_ids: set[str], key: str, limit: int) -> list[dict[str, str]]:
    if len(items) > limit:
        raise ManualWasteError("too_many")
    found: list[dict[str, str]] = []
    for item in items:
        kind = str(item.get("type") or "")
        if kind not in type_ids:
            raise ManualWasteError("unknown_type")
        found.append({key: kind, "date": _day(item.get("date")).isoformat()})
    return sorted(found, key=lambda entry: (entry["date"], entry[key]))


def _series(frequency: str, first: date, end: date) -> list[date]:
    """The pickups of one rule from its first date to ``end``."""
    if frequency != "monthly":
        step = timedelta(days=FREQUENCIES[frequency])
        days: list[date] = []
        day = first
        while day <= end:
            days.append(day)
            day += step
        return days
    days = []
    year, month = first.year, first.month
    while date(year, month, 1) <= end:
        last = month_calendar.monthrange(year, month)[1]
        day = date(year, month, min(first.day, last))
        if first <= day <= end:
            days.append(day)
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return days


def _end_of(schedule: dict[str, list[dict[str, str]]], today: date) -> date:
    """The last day that is written out: two years past the latest date the family gave."""
    dates = [date.fromisoformat(rule["first"]) for rule in schedule["rules"]]
    dates += [date.fromisoformat(item["date"]) for item in schedule["extra"]]
    dates += [date.fromisoformat(item["to"]) for item in schedule["moves"]]
    return max([today, *dates]) + timedelta(days=HORIZON_DAYS)


def _series_of(
    schedule: dict[str, list[dict[str, str]]], today: date | None = None
) -> list[tuple[str, date]]:
    """Every pickup of the rules, the extra dates included, before skips and moves."""
    end = _end_of(schedule, today or date.today())
    found: set[tuple[str, date]] = set()
    for rule in schedule["rules"]:
        first = date.fromisoformat(rule["first"])
        for day in _series(rule["frequency"], first, end):
            found.add((rule["type"], day))
    for item in schedule["extra"]:
        found.add((item["type"], date.fromisoformat(item["date"])))
    return sorted(found, key=lambda pair: (pair[1], pair[0]))


def occurrences(
    schedule: dict[str, list[dict[str, str]]], today: date | None = None
) -> list[tuple[str, date]]:
    """Every pickup as (type id, day): rules and extra dates, minus the skipped days, with the
    moved pickups where they were moved to."""
    skipped = {(item["type"], date.fromisoformat(item["date"])) for item in schedule["skip"]}
    found = {
        pair
        for pair in _series_of(schedule, today)
        if pair not in skipped and ("", pair[1]) not in skipped
    }
    for move in schedule["moves"]:
        source = (move["type"], date.fromisoformat(move["from"]))
        if source in found:
            found.discard(source)
            found.add((move["type"], date.fromisoformat(move["to"])))
    return sorted(found, key=lambda pair: (pair[1], pair[0]))


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics_text(
    schedule: dict[str, list[dict[str, str]]],
    labels: dict[str, str],
    today: date | None = None,
    stamp: datetime | None = None,
) -> str:
    """The pickups as calendar text. Each is an all-day event titled with its type's label, so the
    same classification as a downloaded calendar applies."""
    when = (stamp or datetime(1970, 1, 1)).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Family Hub//Ritiri a mano//IT",
    ]
    for kind, day in occurrences(schedule, today):
        label = labels.get(kind, kind)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{SOURCE_ID}-{kind}-{day.strftime('%Y%m%d')}@family-hub",
            f"DTSTAMP:{when}",
            f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(day + timedelta(days=1)).strftime('%Y%m%d')}",
            f"SUMMARY:{_escape(label)}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def calendar_name(language: str) -> str:
    """The name of the calendar of hand-made pickups, in the family's language."""
    return {
        "it": "Ritiri a mano",
        "de": "Abholungen (von Hand)",
        "en": "Pickups (made by hand)",
    }.get(language, "Pickups (made by hand)")
