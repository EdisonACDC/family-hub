"""0.11.0b4: a guest's date outside the days the server accepts is refused with its own code
("date_range"), not as "invalid", for an ordinary appointment and for each chosen date."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from test_guests import _new

from custom_components.family_hub.guests import GuestError, clean_event

TODAY = date(2026, 11, 23)


def _refused(raw: dict[str, Any]) -> str:
    with pytest.raises(GuestError) as err:
        clean_event(raw, ["sofia"], ["scuola"], TODAY)
    return err.value.code


def test_the_day_before_yesterday_is_refused_with_its_own_code() -> None:
    assert _refused(_new(date=(TODAY - timedelta(days=2)).isoformat())) == "date_range"


def test_two_years_and_a_day_ahead_is_refused_with_its_own_code() -> None:
    assert _refused(_new(date=(TODAY + timedelta(days=732)).isoformat())) == "date_range"


def test_yesterday_and_the_last_allowed_day_are_accepted() -> None:
    for day in (TODAY - timedelta(days=1), TODAY + timedelta(days=731)):
        event = clean_event(_new(date=day.isoformat()), ["sofia"], ["scuola"], TODAY)
        assert event["start"][:10] == day.isoformat()


def test_a_chosen_date_outside_the_window_is_refused_with_its_own_code() -> None:
    skipped = ("date", "start", "end", "all_day")
    raw = {key: value for key, value in _new().items() if key not in skipped}
    raw["dates"] = [
        {"date": (TODAY - timedelta(days=3)).isoformat(), "start": "10:00", "end": "11:00"},
    ]
    assert _refused(raw) == "date_range"
