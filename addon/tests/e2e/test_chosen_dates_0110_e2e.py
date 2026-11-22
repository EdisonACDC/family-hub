"""0.11.0b1: an event on chosen dates. The month shows the dates; a tap picks a day or takes it off;
each date has its own start and end; "Stesso orario per tutte" copies the main times; an end before
its start is shown on its own row and nothing is saved. The event is found in the right weeks."""

from __future__ import annotations

import re
from datetime import date

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_layout_071_e2e import _open, _view
from tests.e2e.test_tablet import _device

SUMMARY = "Recita di Natale"
FIRST = "14/11/2026"
SECOND_DAY = "22"  # in December: the month is changed with the arrow of the calendar


def _added(stack: Stack) -> list[dict[str, object]]:
    return [c["data"] for c in stack.fake.calls if c["service"] == "add_event"]


def _new_chosen(page: Page) -> object:
    page.locator("#add-btn").click()
    form = page.locator("#event-form")
    expect(form).to_be_visible(timeout=3000)
    form.locator("input[name='summary']").fill(SUMMARY)
    form.locator("input[name='date']").fill(FIRST)
    form.locator("#repeat-kind").select_option("chosen")
    expect(page.locator("#chosen-box")).to_be_visible(timeout=3000)
    return form


def _go_to_december(page: Page) -> None:
    page.locator("#chosen-box .month-nav button", has_text="→").click()


def _tap_day(page: Page, day: str) -> None:
    page.locator("#chosen-box .chosen-grid .day-cell", has_text=re.compile(rf"^{day}$")).click()


def _find_in_week(page: Page, day: date) -> None:
    """The week view starts on today and its arrows move seven days: go back to this week, then
    move to the week of ``day`` and look for the event there."""
    page.locator("#this-week").click()
    weeks = (day - date.today()).days // 7
    arrow = page.locator("#next-week" if weeks > 0 else "#prev-week")
    for _ in range(abs(weeks)):
        arrow.click()
    expect(page.locator(".event", has_text=SUMMARY).first).to_be_visible(timeout=5000)


@pytest.mark.parametrize(("width", "height"), [(1280, 800), (390, 844)])
def test_chosen_dates_are_saved_with_their_own_times_and_found_in_their_weeks(
    stack_full: Stack, browser: Browser, width: int, height: int
) -> None:
    stack_full.fake.calls.clear()
    with _device(browser, width, height) as page:
        _open(page, stack_full)
        form = _new_chosen(page)
        # The first date is the one of the form; a second one is picked in December.
        _go_to_december(page)
        _tap_day(page, SECOND_DAY)
        rows = page.locator("#chosen-box .chosen-row")
        expect(rows).to_have_count(2)
        # The December date has its own times, not the main ones.
        rows.nth(1).locator(".chosen-start").fill("18:00")
        rows.nth(1).locator(".chosen-start").press("Tab")
        rows.nth(1).locator(".chosen-end").fill("19:30")
        rows.nth(1).locator(".chosen-end").press("Tab")
        form.locator(".dialog-foot .btn-primary").click()
        expect(page.locator("#event-overlay")).to_be_hidden(timeout=3000)
        if width > 600:  # the week arrows are on the tablet and the computer
            _view(page, "week")
            _find_in_week(page, date(2026, 11, 14))
            _find_in_week(page, date(2026, 12, 22))
    added = _added(stack_full)
    assert added, "the event was sent"
    dates = added[-1]["dates"]
    assert dates == [
        {"start": "2026-11-14 09:00:00", "end": "2026-11-14 10:00:00"},
        {"start": "2026-12-22 18:00:00", "end": "2026-12-22 19:30:00"},
    ], dates
    assert "rrule" not in added[-1]


def test_an_end_before_its_start_is_shown_on_its_row_and_nothing_is_saved(
    stack_full: Stack, browser: Browser
) -> None:
    stack_full.fake.calls.clear()
    with _device(browser, 1280, 800) as page:
        _open(page, stack_full)
        form = _new_chosen(page)
        _go_to_december(page)
        _tap_day(page, SECOND_DAY)
        row = page.locator("#chosen-box .chosen-row").nth(1)
        row.locator(".chosen-end").fill("08:00")
        row.locator(".chosen-end").press("Tab")
        expect(row.locator(".chosen-bad")).to_be_visible(timeout=3000)
        form.locator(".dialog-foot .btn-primary").click()
        expect(page.locator("#event-error")).to_be_visible(timeout=3000)
    assert _added(stack_full) == []


def test_stesso_orario_copies_the_main_times_to_every_date(
    stack_full: Stack, browser: Browser
) -> None:
    stack_full.fake.calls.clear()
    with _device(browser, 1280, 800) as page:
        _open(page, stack_full)
        form = _new_chosen(page)
        _go_to_december(page)
        _tap_day(page, SECOND_DAY)
        rows = page.locator("#chosen-box .chosen-row")
        rows.nth(1).locator(".chosen-start").fill("20:00")
        rows.nth(1).locator(".chosen-start").press("Tab")
        page.locator(
            "#chosen-box button", has_text=re.compile("Stesso orario|Same time|Gleiche Zeit")
        ).click()
        form.locator(".dialog-foot .btn-primary").click()
        expect(page.locator("#event-overlay")).to_be_hidden(timeout=3000)
    dates = _added(stack_full)[-1]["dates"]
    assert [d["start"] for d in dates] == ["2026-11-14 09:00:00", "2026-12-22 09:00:00"], dates
