"""0.11.0b3: "chosen" is read from Home Assistant's text. An ordinary appointment (chosen
"False") is not a series of chosen dates, so chosen_dates refuses it; a real series is found by
its series."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from app.server import Hub


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _hub(events: list[dict[str, Any]]) -> Hub:
    hub = Hub.__new__(Hub)

    async def family_calendars() -> list[dict[str, Any]]:
        return [{"entity_id": "calendar.familia"}]

    async def events_of(entity_id: str, start: str, end: str) -> list[dict[str, Any]]:
        return events

    hub.family_calendars = family_calendars  # type: ignore[method-assign]
    hub._events_of = events_of  # type: ignore[method-assign]
    return hub


def _record(uid: str, chosen: str, series: str, start: str) -> dict[str, Any]:
    # As Home Assistant sends it: a boolean is text.
    return {
        "record_id": uid,
        "chosen": chosen,
        "series": series,
        "start": start,
        "end": start,
        "person_ids": "mamma",
    }


def test_chosen_dates_refuses_an_ordinary_appointment() -> None:
    hub = _hub([_record("visita", "False", "", "2026-11-14 09:00:00")])
    with pytest.raises(ValueError, match="not_chosen_dates"):
        _run(hub.chosen_dates(None, "visita"))  # type: ignore[arg-type]


def test_chosen_dates_lists_the_series_of_a_chosen_appointment() -> None:
    events = [
        _record("a", "True", "s1", "2026-11-14 09:00:00"),
        _record("b", "True", "s1", "2026-12-22 18:00:00"),
        _record("visita", "False", "", "2026-11-20 10:00:00"),
    ]
    hub = _hub(events)
    with patch("app.server.can_change", return_value=True):
        found = _run(hub.chosen_dates(None, "a"))  # type: ignore[arg-type]
    assert [item["record_id"] for item in found] == ["a", "b"]
