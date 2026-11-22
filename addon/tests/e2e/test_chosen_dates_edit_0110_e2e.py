"""0.11.0b1: "Tutti" on an event of chosen dates. The form shows every date of the series, each with
its own times; a new title goes to all of them and the times stay as they were."""

from __future__ import annotations

import re
from datetime import date

from playwright.sync_api import Browser, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_layout_071_e2e import _open, _view
from tests.e2e.test_tablet import _device
from tests.fake_ha import FAMILY, stored_event

SERIES = "serie-recita"
OLD = "Recita di Natale"
NEW = "Concerto di Natale"
DATES = [
    ("2026-11-14 09:00:00", "2026-11-14 10:00:00"),
    ("2026-12-22 18:00:00", "2026-12-22 19:30:00"),
]


def _seed(stack: Stack) -> None:
    # The stack can be shared by the tests of this file: an earlier series is taken away first.
    stack.fake.events[FAMILY][:] = [
        e for e in stack.fake.events[FAMILY] if e.get("series") != SERIES
    ]
    for start, end in DATES:
        record = stored_event(OLD, start, end, "mamma")
        stack.fake.events[FAMILY].append(
            {**record, "chosen": True, "series": SERIES, "all_day": False}
        )


def _find_in_week(page, day: date) -> None:
    page.locator("#this-week").click()
    weeks = (day - date.today()).days // 7
    arrow = page.locator("#next-week" if weeks > 0 else "#prev-week")
    for _ in range(abs(weeks)):
        arrow.click()
    expect(page.locator(".event", has_text=OLD).first).to_be_visible(timeout=5000)


def test_all_changes_the_title_of_every_date_and_keeps_each_time(
    stack_full: Stack, browser: Browser
) -> None:
    _seed(stack_full)
    stack_full.fake.calls.clear()
    with _device(browser, 1280, 800) as page:
        _open(page, stack_full)
        _view(page, "week")
        _find_in_week(page, date(2026, 11, 14))
        page.locator(".event", has_text=OLD).first.click()
        expect(page.locator("#card-overlay")).to_be_visible(timeout=3000)
        page.locator("#card-foot button", has_text=re.compile("Modifica|Edit|Bearbeiten")).click()
        form = page.locator("#event-form")
        expect(form).to_be_visible(timeout=3000)
        # The scope is about the dates: "Tutti" shows them all.
        form.locator("input[name='scope'][value='ALL']").check()
        rows = page.locator("#chosen-box .chosen-row")
        expect(rows).to_have_count(2, timeout=5000)
        form.locator("input[name='summary']").fill(NEW)
        form.locator(".dialog-foot .btn-primary").click()
        expect(page.locator("#event-overlay")).to_be_hidden(timeout=3000)
    updates = [c["data"] for c in stack_full.fake.calls if c["service"] == "update_event"]
    assert updates, "the change was sent"
    sent = updates[-1]
    assert sent["recurrence_range"] == "ALL", sent
    assert sent["summary"] == NEW, sent
    assert sent["dates"] == [{"start": start, "end": end} for start, end in DATES], sent["dates"]


def _absent_in_week(page, day: date) -> None:
    """The week of a day has no appointment of this name (the week view, from today's week)."""
    page.locator("#this-week").click()
    weeks = (day - date.today()).days // 7
    arrow = page.locator("#next-week" if weeks > 0 else "#prev-week")
    for _ in range(abs(weeks)):
        arrow.click()
    expect(page.locator(".event", has_text=OLD)).to_have_count(0, timeout=5000)


def _day_cell(page, number: str):
    return page.locator("#chosen-box .day-cell").filter(
        has=page.locator(".dnum", has_text=re.compile(rf"^{number}$"))
    )


def test_all_adds_a_date_and_takes_another_off_in_the_right_weeks(
    stack_full: Stack, browser: Browser
) -> None:
    _seed(stack_full)
    stack_full.fake.calls.clear()
    with _device(browser, 1280, 800) as page:
        _open(page, stack_full)
        _view(page, "week")
        _find_in_week(page, date(2026, 11, 14))
        page.locator(".event", has_text=OLD).first.click()
        expect(page.locator("#card-overlay")).to_be_visible(timeout=3000)
        page.locator("#card-foot button", has_text=re.compile("Modifica|Edit|Bearbeiten")).click()
        form = page.locator("#event-form")
        expect(form).to_be_visible(timeout=3000)
        form.locator("input[name='scope'][value='ALL']").check()
        rows = page.locator("#chosen-box .chosen-row")
        expect(rows).to_have_count(2, timeout=5000)
        # The December date is taken off: its month, then its day (picked, so it comes off).
        page.locator("#chosen-box .month-nav button", has_text="→").click()
        _day_cell(page, "22").click()
        expect(rows).to_have_count(1)
        # A date in November is added: back to its month, then the day.
        page.locator("#chosen-box .month-nav button", has_text="←").click()
        _day_cell(page, "20").click()
        expect(rows).to_have_count(2)
        form.locator(".dialog-foot .btn-primary").click()
        expect(page.locator("#event-overlay")).to_be_hidden(timeout=3000)
        # The week of the new date shows the appointment; the week of the removed one does not.
        _find_in_week(page, date(2026, 11, 20))
        _absent_in_week(page, date(2026, 12, 22))
    updates = [c["data"] for c in stack_full.fake.calls if c["service"] == "update_event"]
    assert updates[-1]["dates"] == [
        {"start": "2026-11-14 09:00:00", "end": "2026-11-14 10:00:00"},
        {"start": "2026-11-20 09:00:00", "end": "2026-11-20 10:00:00"},
    ], updates[-1]["dates"]
    stored = sorted(e["start"] for e in stack_full.fake.events[FAMILY] if e.get("series") == SERIES)
    assert stored == ["2026-11-14 09:00:00", "2026-11-20 09:00:00"], stored
