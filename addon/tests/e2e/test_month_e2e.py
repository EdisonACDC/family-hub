"""The month view, to find free time: the busy bar counts the hours taken between 07:00 and
21:00 (rubbish and holidays do not count), the person filter keeps one person's events and the
family's, and a free slot of the day opens "Nuovo evento" already filled in."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta

from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_tablet import _shot
from tests.fake_ha import FAMILY, SCHOOL, WASTE, stored_event
from tests.helpers import ADULT_USER


def _day() -> date:
    """A day in the current month (so it is in the grid), not today's busy morning."""
    today = date.today()
    return today if today.day < 25 else today - timedelta(days=3)


@contextmanager
def _seeded(stack: Stack) -> Iterator[str]:
    day = _day().isoformat()
    added = {
        FAMILY: [
            # Mamma 07:00-12:00 and the family 11:00-14:00 (overlap): 7 hours from 07:00 to 14:00.
            stored_event("Lavoro", f"{day} 07:00:00", f"{day} 12:00:00", "mamma"),
            stored_event("Pranzo", f"{day} 11:00:00", f"{day} 14:00:00", ""),
        ],
        SCHOOL: [stored_event("Scuola", f"{day} 15:00:00", f"{day} 17:00:00", "sofia")],
    }
    waste_before = list(stack.fake.events.get(WASTE, []))
    stack.fake.events[WASTE] = [stored_event("Restmüll", day, day)]
    for entity, events in added.items():
        stack.fake.events[entity].extend(events)
    try:
        yield day
    finally:
        for entity, events in added.items():
            for event in events:
                stack.fake.events[entity].remove(event)
        stack.fake.events[WASTE] = waste_before


def _open_month(page: Page, stack: Stack) -> None:
    page.goto(stack.url + "/?lang=it")
    expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
    phone = (page.viewport_size or {}).get("width", 1024) < 600
    page.locator(
        "#tabbar [data-tab='month']" if phone else "#view-switch [data-view='month']"
    ).click()
    expect(page.locator("#month-scroll")).to_be_visible(timeout=5000)


def test_busy_bar_counts_hours_and_not_rubbish(stack_full: Stack, tablet: Page) -> None:
    with _seeded(stack_full) as day:
        _open_month(tablet, stack_full)
        cell = tablet.locator(f".month-day[data-day='{day}']")
        # 07:00-14:00 (merged) + 15:00-17:00 = 9 hours = 540 minutes of 840.
        expect(cell).to_have_attribute("data-busy", "540")
        width = cell.locator(".occ-fill").evaluate("e => e.style.width")
        assert width == "64%", width
        # As many lines as the cell has room for, the rest in "+N altri" (4 events that day).
        # The lines that fit are chosen once the month is drawn: wait for that to settle.
        tablet.wait_for_timeout(300)
        lines = cell.locator(".month-ev:not([hidden])").count()
        assert lines >= 1
        expect(cell.locator(".month-more")).to_have_text(f"+{4 - lines} altri")
        _shot(tablet, "tablet_month")
        # The choice stays on this screen.
        tablet.reload()
        expect(tablet.locator("#month-scroll")).to_be_visible(timeout=5000)
        tablet.locator("#view-switch [data-view='week']").click()
        expect(tablet.locator(".month-view")).to_have_count(0)


def test_person_filter_keeps_that_person_and_the_family(stack_full: Stack, tablet: Page) -> None:
    with _seeded(stack_full) as day:
        _open_month(tablet, stack_full)
        tablet.locator("#persons-bar [data-person='sofia']").click()
        cell = tablet.locator(f".month-day[data-day='{day}']")
        # Sofia: the family lunch 11:00-14:00 and her school 15:00-17:00 = 5 hours.
        expect(cell).to_have_attribute("data-busy", "300")
        expect(cell.locator(".month-ev", has_text="Lavoro")).to_have_count(0)
        tablet.locator("#persons-bar [data-person='mamma']").click()
        expect(cell).to_have_attribute("data-busy", "420")


def test_a_free_slot_opens_new_event_with_date_and_time(stack_full: Stack, tablet: Page) -> None:
    with _seeded(stack_full) as day:
        _open_month(tablet, stack_full)
        tablet.locator(f".month-day[data-day='{day}']").click(position={"x": 8, "y": 8})
        dayview = tablet.locator(".dayview")
        expect(dayview).to_be_visible()
        slots = dayview.locator(".free-slot")
        # Free: 14:00-15:00 and 17:00-21:00.
        expect(slots).to_have_count(2)
        expect(slots.nth(0)).to_have_attribute("data-from", "14:00")
        expect(slots.nth(1)).to_have_attribute("data-to", "21:00")
        # Shown, but not counted: the rubbish calendar of Home Assistant.
        expect(dayview.locator(".day-note", has_text="Restmüll")).to_be_visible()
        _shot(tablet, "tablet_day_free_slots")
        slots.nth(1).click()
        form = tablet.locator("#event-form")
        expect(tablet.locator("#event-overlay")).to_be_visible()
        expect(tablet.locator("#event-title")).to_have_text("Nuovo evento")
        expected = date.fromisoformat(day).strftime("%d/%m/%Y")
        expect(form.locator("input[name='date']")).to_have_value(expected)
        expect(form.locator("input[name='start_time']")).to_have_value("17:00")
        expect(form.locator("input[name='end_time']")).to_have_value("18:00")


def test_phone_shows_a_compact_month_with_dots(stack_full: Stack, browser: Browser) -> None:
    context = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True)
    context.set_extra_http_headers({"X-Remote-User-Id": ADULT_USER})
    page = context.new_page()
    try:
        with _seeded(stack_full) as day:
            _open_month(page, stack_full)
            expect(page.locator(".week.month.compact")).to_be_visible()
            cell = page.locator(f".month-day[data-day='{day}']")
            expect(cell.locator(".month-dot")).to_have_count(4)
            expect(cell.locator(".month-ev")).to_have_count(0)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            _shot(page, "phone_month")
            # On the phone the chosen day is shown under the month.
            cell.click(position={"x": 8, "y": 8})
            expect(cell).to_have_class(re.compile("selected"))
            expect(page.locator("#month-day-panel .busy-name").first).to_be_visible()
    finally:
        context.close()
