"""0.11.0b2: a series of chosen dates. The card names its dates ("+N" after five); a row is one line
(a phone: a second line for the switch and the ×); "Tutti" and "Questo e i successivi" delete what
they say; a series saved without a person and with "Privato" off is not private."""

from __future__ import annotations

import re
from datetime import date

from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_layout_071_e2e import _open, _view
from tests.e2e.test_share_090_e2e import DEVICE
from tests.e2e.test_tablet import _device
from tests.fake_ha import FAMILY, stored_event

SERIES = "serie-b2"
SUMMARY = "Recita di Natale"
DATES = [
    ("2026-11-14 09:00:00", "2026-11-14 10:00:00"),
    ("2026-12-22 18:00:00", "2026-12-22 19:30:00"),
]


def _seed(stack: Stack, dates: list[tuple[str, str]] = DATES, guests: bool = False) -> None:
    # The stack can be shared by the tests of this file: an earlier series is taken away first.
    stack.fake.events[FAMILY][:] = [
        e for e in stack.fake.events[FAMILY] if e.get("series") != SERIES
    ]
    for start, end in dates:
        record = stored_event(SUMMARY, start, end, "mamma")
        stack.fake.events[FAMILY].append(
            {**record, "chosen": True, "series": SERIES, "all_day": False}
        )
    devices = [{**DEVICE, "status": "active"}] if guests else []
    stack.fake.guest.update({"invites": [], "devices": devices, "pending": [], "log": []})
    stack.fake.calls.clear()


def _series(stack: Stack) -> list[str]:
    return sorted(e["start"] for e in stack.fake.events[FAMILY] if e.get("series") == SERIES)


def _find_in_week(page: Page, day: date) -> None:
    """The week view starts on today and its arrows move seven days: go back to this week, then
    move to the week of ``day`` and look for the event there."""
    page.locator("#this-week").click()
    weeks = (day - date.today()).days // 7
    arrow = page.locator("#next-week" if weeks > 0 else "#prev-week")
    for _ in range(abs(weeks)):
        arrow.click()
    expect(page.locator(".event", has_text=SUMMARY).first).to_be_visible(timeout=5000)


def _open_card(page: Page, day: date) -> None:
    _find_in_week(page, day)
    page.locator(".event", has_text=SUMMARY).first.click()
    expect(page.locator("#card-overlay")).to_be_visible(timeout=3000)


def _new_chosen(page: Page, summary: str) -> object:
    page.locator("#add-btn").click()
    form = page.locator("#event-form")
    expect(form).to_be_visible(timeout=3000)
    form.locator("input[name='summary']").fill(summary)
    form.locator("input[name='date']").fill("14/11/2026")
    form.locator("#repeat-kind").select_option("chosen")
    expect(page.locator("#chosen-box")).to_be_visible(timeout=3000)
    return form


def _tap_day(page: Page, day: str) -> None:
    page.locator("#chosen-box .chosen-grid .day-cell", has_text=re.compile(rf"^{day}$")).click()


def test_the_card_names_the_dates_of_the_series(stack_full: Stack, browser: Browser) -> None:
    _seed(stack_full)
    with _device(browser, 1280, 800) as page:
        _open(page, stack_full)
        _view(page, "week")
        _open_card(page, date(2026, 11, 14))
        expect(page.locator(".card-chosen")).to_have_text(
            "Date scelte: 14/11, 22/12 (2 date)", timeout=5000
        )


def test_more_than_five_dates_are_counted_after_the_first_five(
    stack_full: Stack, browser: Browser
) -> None:
    dates = [(f"2026-11-{d:02d} 09:00:00", f"2026-11-{d:02d} 10:00:00") for d in range(10, 17)]
    _seed(stack_full, dates)
    with _device(browser, 1280, 800) as page:
        _open(page, stack_full)
        _view(page, "week")
        _open_card(page, date(2026, 11, 10))
        expect(page.locator(".card-chosen")).to_have_text(
            "Date scelte: 10/11, 11/11, 12/11, 13/11, 14/11 +2 (7 date)", timeout=5000
        )


def test_a_date_is_one_line_on_the_tablet_and_two_on_the_phone(
    stack_full: Stack, browser: Browser
) -> None:
    _seed(stack_full)
    with _device(browser, 1280, 800) as page:
        _open(page, stack_full)
        _new_chosen(page, "Riga larga")
        _go_to_december(page)
        _tap_day(page, "22")
        row = page.locator("#chosen-box .chosen-row").nth(1)
        expect(row).to_be_visible()
        start = row.locator(".chosen-start").bounding_box()
        end = row.locator(".chosen-end").bounding_box()
        switch = row.locator(".chosen-allday").bounding_box()
        assert start and end and switch
        middle = start["y"] + start["height"] / 2
        assert abs(end["y"] + end["height"] / 2 - middle) < 8, "Inizio and Fine share the line"
        assert abs(switch["y"] + switch["height"] / 2 - middle) < 12, (
            "the switch is on the line too"
        )
        # "Tutto il giorno" on: the times of that date are not shown.
        row.locator(".chosen-allday input").check()
        expect(row.locator(".chosen-start")).to_have_count(0)
    with _device(browser, 390, 844) as page:
        _open(page, stack_full)
        _new_chosen(page, "Riga stretta")
        _go_to_december(page)
        _tap_day(page, "22")
        row = page.locator("#chosen-box .chosen-row").nth(1)
        expect(row).to_be_visible()
        start = row.locator(".chosen-start").bounding_box()
        switch = row.locator(".chosen-allday").bounding_box()
        assert start and switch
        assert switch["y"] > start["y"] + start["height"] / 2, "on a phone the switch is below"
        overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        assert overflow <= 0, f"no horizontal scroll on the phone ({overflow}px over)"


def test_all_deletes_every_date_of_the_series(stack_full: Stack, browser: Browser) -> None:
    _seed(stack_full)
    with _device(browser, 1280, 800) as page:
        _open(page, stack_full)
        _view(page, "week")
        _open_card(page, date(2026, 11, 14))
        page.locator("#card-foot button", has_text=re.compile("Elimina|Delete|Löschen")).click()
        expect(page.locator("#scope-overlay")).to_be_visible(timeout=3000)
        page.locator("#scope-all").click()
        expect(page.locator("#card-overlay")).to_be_hidden(timeout=3000)
    deletes = [c["data"] for c in stack_full.fake.calls if c["service"] == "delete_event"]
    assert deletes and deletes[-1]["recurrence_range"] == "ALL", deletes
    assert _series(stack_full) == [], "every date is gone"


def test_this_and_the_following_deletes_from_the_date_on(
    stack_full: Stack, browser: Browser
) -> None:
    third = ("2027-01-06 09:00:00", "2027-01-06 09:30:00")
    _seed(stack_full, [*DATES, third])
    with _device(browser, 1280, 800) as page:
        _open(page, stack_full)
        _view(page, "week")
        _open_card(page, date(2026, 12, 22))
        page.locator("#card-foot button", has_text=re.compile("Elimina|Delete|Löschen")).click()
        expect(page.locator("#scope-overlay")).to_be_visible(timeout=3000)
        page.locator("#scope-future").click()
        expect(page.locator("#card-overlay")).to_be_hidden(timeout=3000)
    deletes = [c["data"] for c in stack_full.fake.calls if c["service"] == "delete_event"]
    assert deletes and deletes[-1]["recurrence_range"] == "THISANDFUTURE", deletes
    assert _series(stack_full) == ["2026-11-14 09:00:00"], _series(stack_full)


def _go_to_december(page: Page) -> None:
    page.locator("#chosen-box .month-nav button", has_text="→").click()


def test_a_series_without_a_person_is_not_private_after_the_warning_and_a_time_fix(
    stack_full: Stack, browser: Browser
) -> None:
    # Guests are on, so the family's own appointment needs a person or "Salva comunque".
    _seed(stack_full, guests=True)
    summary = "Recita senza persona"
    with _device(browser, 1280, 800) as page:
        _open(page, stack_full)
        form = _new_chosen(page, summary)
        _go_to_december(page)
        _tap_day(page, "22")
        row = page.locator("#chosen-box .chosen-row").nth(1)
        row.locator(".chosen-end").fill("08:00")
        row.locator(".chosen-end").press("Tab")
        form.locator(".dialog-foot .btn-primary").click()
        expect(page.locator("#no-person-warning")).to_be_visible(timeout=3000)
        expect(page.locator("#event-private")).not_to_be_checked()
        # "Salva comunque": the time is still wrong, so the error shows and nothing is saved.
        page.click("#no-person-save")
        expect(page.locator("#event-error")).to_be_visible(timeout=3000)
        assert not [c for c in stack_full.fake.calls if c["service"] == "add_event"]
        # The time is fixed and the form is sent again.
        row.locator(".chosen-end").fill("19:30")
        row.locator(".chosen-end").press("Tab")
        expect(page.locator("#event-private")).not_to_be_checked()
        form.locator(".dialog-foot .btn-primary").click()
        expect(page.locator("#event-form")).to_be_hidden(timeout=3000)
    added = [c["data"] for c in stack_full.fake.calls if c["service"] == "add_event"]
    assert len(added) == 1, added
    assert "private" not in added[0], added[0]
    saved = [e for e in stack_full.fake.events[FAMILY] if e["summary"] == summary]
    assert saved and not any(e.get("private") for e in saved), saved
