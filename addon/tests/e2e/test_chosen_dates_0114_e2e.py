"""0.11.0b4: in a series of chosen dates, the message "the end must be after the start" goes away as
soon as the row is valid (not only at the next save), and the switch "Tutto il giorno" keeps a space
before the ×."""

from __future__ import annotations

import re

from playwright.sync_api import Browser, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_layout_071_e2e import _open
from tests.e2e.test_tablet import _device


def _new_chosen(page) -> object:  # type: ignore[no-untyped-def]
    page.locator("#add-btn").click()
    form = page.locator("#event-form")
    expect(form).to_be_visible(timeout=3000)
    form.locator("input[name='summary']").fill("Recita di Natale")
    form.locator("input[name='date']").fill("14/11/2026")
    form.locator("#repeat-kind").select_option("chosen")
    expect(page.locator("#chosen-box")).to_be_visible(timeout=3000)
    return form


def test_the_end_message_goes_as_soon_as_the_row_is_valid(
    stack_full: Stack, browser: Browser
) -> None:
    stack_full.fake.calls.clear()
    with _device(browser, 1280, 800) as page:
        _open(page, stack_full)
        form = _new_chosen(page)
        page.locator("#chosen-box .month-nav button", has_text="→").click()
        page.locator("#chosen-box .chosen-grid .day-cell", has_text=re.compile(r"^22$")).click()
        row = page.locator("#chosen-box .chosen-row").nth(1)
        row.locator(".chosen-end").fill("08:00")
        row.locator(".chosen-end").press("Tab")
        # Saving with the wrong end shows the message on the form.
        form.locator(".dialog-foot .btn-primary").click()
        expect(page.locator("#event-error")).to_be_visible(timeout=3000)
        # The end is fixed: the message goes now, before any save.
        row.locator(".chosen-end").fill("19:30")
        row.locator(".chosen-end").press("Tab")
        expect(page.locator("#event-error")).to_be_hidden(timeout=3000)
        assert not [c for c in stack_full.fake.calls if c["service"] == "add_event"]


def test_the_switch_keeps_a_space_before_the_remove_button(
    stack_full: Stack, browser: Browser
) -> None:
    stack_full.fake.calls.clear()
    with _device(browser, 1280, 800) as page:
        _open(page, stack_full)
        _new_chosen(page)
        page.locator("#chosen-box .chosen-grid .day-cell", has_text=re.compile(r"^15$")).click()
        row = page.locator("#chosen-box .chosen-row").first
        expect(row).to_be_visible(timeout=3000)
        switch = row.locator(".chosen-allday").bounding_box()
        remove = row.locator(".chosen-remove").bounding_box()
        assert switch and remove
        gap = remove["x"] - (switch["x"] + switch["width"])
        assert gap >= 8, f"only {gap:.0f}px between the switch and the remove button"


def test_an_adult_can_pick_any_day_of_the_month(stack_full: Stack, browser: Browser) -> None:
    # The days a guest may not choose are for the invited only: the family picks any day.
    stack_full.fake.calls.clear()
    with _device(browser, 1280, 800) as page:
        _open(page, stack_full)
        _new_chosen(page)
        expect(page.locator("#chosen-box .chosen-grid .day-cell").first).to_be_enabled()
        expect(page.locator("#chosen-box .chosen-grid .day-cell:disabled")).to_have_count(0)
