"""Repeating events: the repeat rule (iCalendar RRULE text) and the dates it gives.

A repeating event is kept as one record per occurrence, all sharing a series id. That way reminders,
colours, the month and list views, free time and summaries see plain events. The occurrences are
written out up to a horizon (see HORIZON_DAYS) and extended each day.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from itertools import islice
from typing import Any

from dateutil.rrule import rrulestr

FREQUENCIES = ("DAILY", "WEEKLY", "MONTHLY", "YEARLY")
# How far past now the occurrences are written out. Extended each day, so it never runs out.
HORIZON_DAYS = 400
MAX_OCCURRENCES = 1000


class RecurrenceError(ValueError):
    """A repeat rule that cannot be used. ``code`` says why, for the page to explain."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _parts(rule: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    for item in rule.split(";"):
        if "=" not in item:
            raise RecurrenceError("invalid_rule")
        key, value = item.split("=", 1)
        parts[key.strip().upper()] = value.strip().upper()
    return parts


def validate(rule: str | None) -> str:
    """Check a repeat rule and return it in the stored form. Raises RecurrenceError."""
    text = str(rule or "").strip()
    if text.upper().startswith("RRULE:"):
        text = text[6:]
    parts = _parts(text)
    if parts.get("FREQ") not in FREQUENCIES:
        raise RecurrenceError("invalid_rule")
    if "UNTIL" in parts and "COUNT" in parts:
        raise RecurrenceError("invalid_rule")
    try:
        # The library must read it too: a rule it cannot read is refused here, not later.
        list(islice(rrulestr(text, dtstart=datetime(2026, 1, 1, 12)), 1))
    except (ValueError, TypeError, KeyError) as err:
        raise RecurrenceError("invalid_rule") from err
    return text.upper()


def _cutoff(parts: dict[str, str], tz: Any) -> datetime | None:
    """The last moment of an UNTIL date (or date and time), in the first day's time zone."""
    text = parts.get("UNTIL")
    if not text:
        return None
    if "T" in text:
        moment = datetime.strptime(text.rstrip("Z"), "%Y%m%dT%H%M%S")
        return moment.replace(tzinfo=tz)
    day = datetime.strptime(text[:8], "%Y%m%d")
    return (day + timedelta(days=1)).replace(tzinfo=tz)


def _within(rule: str, first: datetime, horizon: datetime) -> list[datetime]:
    """The occurrences from first (always included) up to horizon.

    UNTIL is applied here, not by the library: the library refuses an UNTIL date with a time zone.
    """
    parts = _parts(rule)
    library = ";".join(item for item in rule.split(";") if not item.upper().startswith("UNTIL="))
    cutoff = _cutoff(parts, first.tzinfo)
    end = min(horizon, cutoff) if cutoff is not None else horizon
    found = [first]
    rr = rrulestr(library, dtstart=first)
    for when in islice(rr, MAX_OCCURRENCES):
        if when > end:
            break
        if when != first:
            found.append(when)
    return found


def starts_for(rule: str, first: datetime, until: datetime) -> list[datetime]:
    """The start of every occurrence of ``rule`` that begins at ``first``, up to ``until``."""
    return _within(rule, first, until)


def horizon_for(now: datetime, latest: datetime) -> datetime:
    """How far the occurrences are written: a year and more past the later of now and the last
    known date."""
    return max(now, latest) + timedelta(days=HORIZON_DAYS)


def all_day_starts(rule: str, first: date, until: date) -> list[date]:
    """The dates of an all-day series (the rule works on days)."""
    found = _within(
        rule,
        datetime.combine(first, time(0)),
        datetime.combine(until, time(0)),
    )
    return [when.date() for when in found]


def describe(rule: str) -> dict[str, Any]:
    """The rule's parts, for the page (frequency, weekdays, interval, end)."""
    parts = _parts(rule)
    return {
        "freq": parts.get("FREQ", ""),
        "interval": int(parts.get("INTERVAL", "1") or 1),
        "byday": parts.get("BYDAY", ""),
        "count": int(parts["COUNT"]) if "COUNT" in parts else None,
        "until": parts.get("UNTIL", ""),
    }


def remaining(rule: str, before: int) -> str:
    """The rule for the occurrences after ``before`` of its own: a count is what is left."""
    parts = _parts(rule)
    if "COUNT" not in parts:
        return rule
    left = max(int(parts["COUNT"]) - before, 0)
    items = rule.split(";")
    return ";".join(
        f"COUNT={left}" if item.upper().startswith("COUNT=") else item for item in items
    )


def complete(rule: str, horizon: datetime, generated: int) -> bool:
    """True when every occurrence of the rule is already written: its count is reached, or its
    end date is before the horizon."""
    parts = _parts(rule)
    if "COUNT" in parts:
        return generated >= int(parts["COUNT"])
    if "UNTIL" in parts:
        return horizon.strftime("%Y%m%d") >= parts["UNTIL"][:8]
    return False


def ended_rule(rule: str, count: int, last: date) -> str:
    """The rule of the occurrences left after a change, so that the rule says the same as the dates:
    a count becomes the number left, an end date becomes the last one left."""
    items = rule.split(";")
    upper = [item.upper() for item in items]
    if any(item.startswith("COUNT=") for item in upper):
        return ";".join(
            f"COUNT={count}" if item.upper().startswith("COUNT=") else item for item in items
        )
    if any(item.startswith("UNTIL=") for item in upper):
        return ";".join(
            f"UNTIL={last.strftime('%Y%m%d')}" if item.upper().startswith("UNTIL=") else item
            for item in items
        )
    return rule
