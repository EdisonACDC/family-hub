"""Rubbish pickups made by hand: the dates a rule gives, skipped and moved pickups, the checks on
what the page sends, and the calendar text that the rest of Family Hub reads like a file."""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.family_hub import manual_waste as mw
from custom_components.family_hub.external import parse
from custom_components.family_hub.waste import default_waste_types, type_of, types_from_options

TODAY = date(2026, 11, 10)
TYPE_IDS = {kind["id"] for kind in default_waste_types("it")}


def _schedule(**parts: list) -> dict:
    base = mw.empty()
    base.update(parts)
    return mw.normalize(base, TYPE_IDS)


def _days(schedule: dict, kind: str | None = None) -> list[str]:
    return [
        day.isoformat()
        for item_kind, day in mw.occurrences(schedule, TODAY)
        if kind is None or item_kind == kind
    ]


def test_every_two_weeks_from_the_third_of_november() -> None:
    """The example: a pickup every 2 weeks from 3/11 gives 3/11, 17/11 and 1/12."""
    schedule = _schedule(
        rules=[{"type": "bio", "frequency": "biweekly", "weekday": "tue", "first": "2026-11-03"}]
    )
    days = _days(schedule, "bio")
    assert days[:3] == ["2026-11-03", "2026-11-17", "2026-12-01"]
    assert "2026-11-10" not in days


def test_a_skipped_date_does_not_appear() -> None:
    schedule = _schedule(
        rules=[{"type": "bio", "frequency": "biweekly", "weekday": "tue", "first": "2026-11-03"}],
        skip=[{"type": "bio", "date": "2026-11-17"}],
    )
    assert "2026-11-17" not in _days(schedule)
    assert "2026-12-01" in _days(schedule)


def test_a_skip_with_no_type_applies_to_every_type() -> None:
    schedule = _schedule(
        rules=[
            {"type": "bio", "frequency": "weekly", "weekday": "tue", "first": "2026-11-03"},
            {"type": "papier", "frequency": "weekly", "weekday": "tue", "first": "2026-11-03"},
        ],
        skip=[{"type": "", "date": "2026-11-17"}],
    )
    assert "2026-11-17" not in _days(schedule)


def test_an_added_date_appears() -> None:
    schedule = _schedule(extra=[{"type": "glas", "date": "2026-12-24"}])
    assert ("glas", date(2026, 12, 24)) in mw.occurrences(schedule, TODAY)


def test_a_moved_pickup_is_where_it_was_moved_to() -> None:
    schedule = _schedule(
        rules=[{"type": "bio", "frequency": "biweekly", "weekday": "tue", "first": "2026-11-03"}],
        moves=[{"type": "bio", "from": "2026-11-17", "to": "2026-11-18"}],
    )
    days = _days(schedule, "bio")
    assert "2026-11-17" not in days
    assert "2026-11-18" in days


def test_a_monthly_pickup_keeps_its_day_and_takes_the_last_day_of_a_short_month() -> None:
    schedule = _schedule(rules=[{"type": "papier", "frequency": "monthly", "first": "2026-01-31"}])
    days = _days(schedule, "papier")
    assert days[:3] == ["2026-01-31", "2026-02-28", "2026-03-31"]


def test_a_four_weekly_pickup_is_twenty_eight_days_apart() -> None:
    schedule = _schedule(
        rules=[{"type": "gelb", "frequency": "four_weeks", "weekday": "mon", "first": "2026-11-02"}]
    )
    days = [date.fromisoformat(d) for d in _days(schedule, "gelb")]
    assert (days[1] - days[0]).days == 28


@pytest.mark.parametrize(
    ("rule", "code"),
    [
        (
            {"type": "bio", "frequency": "biweekly", "weekday": "wed", "first": "2026-11-03"},
            "weekday_mismatch",
        ),
        (
            {"type": "nope", "frequency": "weekly", "weekday": "tue", "first": "2026-11-03"},
            "unknown_type",
        ),
        (
            {"type": "bio", "frequency": "daily", "weekday": "tue", "first": "2026-11-03"},
            "invalid_frequency",
        ),
        (
            {"type": "bio", "frequency": "weekly", "weekday": "tue", "first": "3 novembre"},
            "invalid_date",
        ),
    ],
)
def test_a_rule_that_cannot_be_used_says_why(rule: dict, code: str) -> None:
    with pytest.raises(mw.ManualWasteError) as err:
        _schedule(rules=[rule])
    assert err.value.code == code


def test_a_type_can_have_only_one_rule() -> None:
    rule = {"type": "bio", "frequency": "weekly", "weekday": "tue", "first": "2026-11-03"}
    with pytest.raises(mw.ManualWasteError) as err:
        _schedule(rules=[rule, dict(rule)])
    assert err.value.code == "type_twice"


def test_a_move_needs_a_pickup_to_move() -> None:
    with pytest.raises(mw.ManualWasteError) as err:
        _schedule(
            rules=[{"type": "bio", "frequency": "weekly", "weekday": "tue", "first": "2026-11-03"}],
            moves=[{"type": "bio", "from": "2026-11-04", "to": "2026-11-05"}],
        )
    assert err.value.code == "move_not_found"


def test_the_calendar_text_reads_like_a_file_and_is_classified_as_rubbish() -> None:
    """The pickups are written as calendar text: parsed by the same reader as a downloaded file,
    titled with the family's label for the type, so the usual rubbish classification applies."""
    types = types_from_options({"language": "it"})
    labels = {kind["id"]: kind["label"] for kind in types}
    schedule = _schedule(
        rules=[{"type": "bio", "frequency": "biweekly", "weekday": "tue", "first": "2026-11-03"}]
    )
    calendar = parse(mw.ics_text(schedule, labels, today=TODAY))
    summaries = [str(event.summary) for event in calendar.events]
    assert summaries.count(labels["bio"]) == len(_days(schedule, "bio"))
    assert type_of(labels["bio"], types)["id"] == "bio"


def test_the_empty_schedule_has_no_pickups() -> None:
    assert mw.occurrences(mw.empty(), TODAY) == []
    assert mw.ics_text(mw.empty(), {}, today=TODAY).count("BEGIN:VEVENT") == 0
