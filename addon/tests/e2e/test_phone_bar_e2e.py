"""The phone's top bar at 390x844 and 360x780: nothing leaves the screen (only the rows made to
scroll sideways may be wider), the bar takes at most about a third of the height, the lists are
in the menu; and the event form offers only Family Hub calendars."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_external_e2e import _add_rubbish_calendar, _remove_rubbish_calendar
from tests.e2e.test_tablet import _shot
from tests.helpers import ADULT_USER

# Every visible element that ends past the right edge, outside the rows that scroll sideways.
OVERFLOW = """() => {
  const width = window.innerWidth;
  const scrollers = ['.filters', '.pickups', '.week', '#menu', '.persons-bar'];
  const out = [];
  for (const e of document.querySelectorAll('body *')) {
    if (scrollers.some(s => e.closest(s))) continue;
    if (e.closest('[hidden]')) continue;
    const r = e.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const name = e.id ? '#' + e.id : e.className || e.tagName;
    if (r.right > width + 1) out.push(name + ' ' + Math.round(r.right));
  }
  return out;
}"""


@contextmanager
def _phone(browser: Browser, width: int, height: int) -> Iterator[Page]:
    context = browser.new_context(
        viewport={"width": width, "height": height}, has_touch=True, is_mobile=True
    )
    context.set_extra_http_headers({"X-Remote-User-Id": ADULT_USER})
    page = context.new_page()
    try:
        yield page
    finally:
        context.close()


@pytest.mark.parametrize(("width", "height"), [(390, 844), (360, 780)])
def test_the_phone_bar_stays_on_screen(
    stack_full: Stack, browser: Browser, width: int, height: int
) -> None:
    today = date.today()
    key = "calendar.family_hub_ext_telefono"
    _add_rubbish_calendar(
        stack_full,
        key,
        "telefono",
        [
            {
                "summary": title,
                "start": (today + timedelta(days=i)).isoformat(),
                "end": (today + timedelta(days=i + 1)).isoformat(),
                "location": "",
                "record_id": "",
                "shift_id": "",
                "person_ids": "",
            }
            for i, title in enumerate(["Abfuhr: Umido", "Abfuhr: Carta", "Abfuhr: Plastica"])
        ],
    )
    try:
        with _phone(browser, width, height) as page:
            page.goto(stack_full.url + "/?lang=it")
            expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
            for selector in ("#menu-btn", "#period-title", "#tabbar", "#add-btn", "#persons-bar"):
                box = page.locator(selector).bounding_box()
                assert box and box["x"] >= -1 and box["x"] + box["width"] <= width + 1, (
                    selector,
                    box,
                )
            assert page.evaluate(OVERFLOW) == []
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            bar = page.locator(".topbar").bounding_box()
            assert bar and bar["height"] <= 56, bar
            # The persons' chips scroll sideways in their row under the bar.
            persons = page.locator("#persons-bar")
            assert persons.evaluate("e => getComputedStyle(e).overflowX") == "auto"
            _shot(page, f"phone_bar_{width}")
            # Liste is a tab at the bottom.
            expect(page.locator("#todo-btn")).to_be_hidden()
            page.locator("#tabbar [data-tab='lists']").click()
            expect(page.locator("#todo-overlay")).to_be_visible()
    finally:
        _remove_rubbish_calendar(stack_full, key, "telefono")


def test_the_event_form_offers_only_family_hub_calendars(stack_full: Stack, tablet: Page) -> None:
    tablet.goto(stack_full.url + "/?lang=it")
    expect(tablet.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
    tablet.locator("#add-btn").click()
    options = tablet.locator("#event-form select[name='category'] option")
    expect(options.first).to_be_attached()
    values = options.evaluate_all("os => os.map(o => o.value)")
    assert values and all(values), values
    names = options.evaluate_all("os => os.map(o => o.textContent)")
    assert "Rifiuti" not in names
    expect(tablet.locator("#event-category-hint")).to_have_text(
        "Per chi? Scegli le persone qui sotto."
    )
