"""0.7.0 layout at 894x727, 1280x800, 1920x1080 (tablet and PC) and 390x844, 360x780 (phone).

Tablet/PC: one top bar of about 64 px, a second row of about 40 px, the calendar takes at least
80% of the height, "+ Nuovo" is in the top bar (no round button over the days), the next 14
days only from 1400 px. Phone: one bar of at most 56 px, four tabs at the bottom, a 56 px +
above them that never covers an event, everything at least 44x44 px and within the width.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_tablet import _shot
from tests.fake_ha import FAMILY, stored_event
from tests.helpers import ADULT_USER

OVERFLOW = """() => {
  const width = window.innerWidth;
  const scrollers = ['.pickups', '.week', '#menu', '.calendars-panel', '.overlay'];
  const out = [];
  for (const e of document.querySelectorAll('body *')) {
    if (scrollers.some(s => e.closest(s))) continue;
    if (e.closest('[hidden]')) continue;
    const r = e.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (r.right > width + 1 || r.left < -1) {
      const cls = typeof e.className === 'string' ? e.className : '';
      const name = e.id ? '#' + e.id : (cls || e.tagName);
      out.push(name + ' ' + Math.round(r.left) + '-' + Math.round(r.right));
    }
  }
  return out;
}"""


@contextmanager
def _screen(browser: Browser, width: int, height: int) -> Iterator[Page]:
    phone = width < 600
    context = browser.new_context(
        viewport={"width": width, "height": height}, has_touch=phone, is_mobile=phone
    )
    context.set_extra_http_headers({"X-Remote-User-Id": ADULT_USER})
    page = context.new_page()
    try:
        page.goto("about:blank")
        yield page
    finally:
        context.close()


@contextmanager
def _busy_week(stack: Stack) -> Iterator[None]:
    """A few events every day, so the screens are full as on a real family tablet."""
    today = date.today()
    added: list[dict[str, Any]] = []
    for i in range(14):
        day = today + timedelta(days=i)
        for hour, title in ((8, "Scuola"), (13, "Pranzo"), (17, "Allenamento"), (20, "Riunione")):
            added.append(
                stored_event(
                    f"{title} {i}", f"{day} {hour:02d}:00:00", f"{day} {hour + 1:02d}:00:00"
                )
            )
    stack.fake.events[FAMILY].extend(added)
    try:
        yield
    finally:
        for event in added:
            stack.fake.events[FAMILY].remove(event)


def _ready(page: Page, stack: Stack) -> None:
    page.goto(stack.url + "/?lang=it")
    expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)


def _view(page: Page, view: str) -> None:
    phone = page.viewport_size and page.viewport_size["width"] < 600
    selector = f"#tabbar [data-tab='{view}']" if phone else f"#view-switch [data-view='{view}']"
    page.locator(selector).click()


@pytest.mark.parametrize(("width", "height"), [(894, 727), (1280, 800), (1920, 1080)])
def test_tablet_and_pc_bars_and_calendar_height(
    stack_full: Stack, browser: Browser, width: int, height: int
) -> None:
    with _busy_week(stack_full), _screen(browser, width, height) as page:
        _ready(page, stack_full)
        expect(page.locator("#week .day")).to_have_count(7, timeout=5000)
        top = page.locator("#topbar").bounding_box()
        sub = page.locator("#subbar").bounding_box()
        week = page.locator("#week").bounding_box()
        assert top and sub and week
        # One row from 1100 px; two rows (the views and the period under) below 1100 px.
        assert top["height"] <= (110 if width < 1100 else 66), top
        assert 46 <= sub["height"] <= 50, sub
        buttons = page.locator("#subbar button").evaluate_all(
            "bs => bs.filter(b => b.offsetParent !== null)"
            ".map(b => b.getBoundingClientRect().height)"
        )
        assert buttons and min(buttons) >= 40, buttons
        assert week["height"] >= (0.7 if width < 1100 else 0.8) * height - 1, (
            week["height"],
            height,
        )
        # "+ Nuovo" sits in the top bar; there is no round button over the days.
        add = page.locator("#add-btn").bounding_box()
        assert add and add["y"] + add["height"] <= top["y"] + top["height"] + 1, add
        assert add["height"] >= 44 - 1
        expect(page.locator("#add-btn .add-label")).to_be_visible()
        # The guide is in the menu, not in the bar; Liste and ☰ Menu are in the bar.
        expect(page.locator("#wizard-start")).to_be_hidden()
        expect(page.locator("#todo-btn")).to_be_visible()
        expect(page.locator("#menu-btn")).to_be_visible()
        expect(page.locator("#period-title")).not_to_be_empty()
        # The next 14 days only from 1400 px.
        if width >= 1400:
            expect(page.locator("#upcoming")).to_be_visible()
        else:
            expect(page.locator("#upcoming")).to_be_hidden()
        assert page.evaluate(OVERFLOW) == []
        _shot(page, f"layout_{width}_week")
        # Calendari: a panel of switches instead of chips.
        page.locator("#calendars-btn").click()
        panel = page.locator("#filters")
        expect(panel).to_be_visible()
        expect(panel.locator(".cal-switch").first).to_be_visible()
        _shot(page, f"layout_{width}_calendars")
        page.locator("#calendars-btn").click()
        expect(panel).to_be_hidden()
        # Month: the weeks of this month fill the area, then it scrolls.
        _view(page, "month")
        key = f"{date.today().year}-{date.today().month:02d}"
        block = page.locator(f".month-block[data-month='{key}']")
        expect(block).to_have_class("month-block loaded", timeout=5000)
        scroller = page.locator("#month-scroll").bounding_box()
        box = block.bounding_box()
        assert scroller and box and box["height"] <= scroller["height"] + 4, (box, scroller)
        assert scroller["height"] >= 0.7 * height, scroller
        _shot(page, f"layout_{width}_month")
        _view(page, "list")
        expect(page.locator("#list-scroll .list-row").first).to_be_visible(timeout=5000)
        _shot(page, f"layout_{width}_list")
        _view(page, "week")


@pytest.mark.parametrize(("width", "height"), [(390, 844), (360, 780)])
def test_phone_bars_tabs_and_the_plus_never_covers_an_event(
    stack_full: Stack, browser: Browser, width: int, height: int
) -> None:
    with _busy_week(stack_full), _screen(browser, width, height) as page:
        _ready(page, stack_full)
        top = page.locator("#topbar").bounding_box()
        assert top and top["height"] <= 56, top
        tabbar = page.locator("#tabbar")
        expect(tabbar).to_be_visible()
        bar = tabbar.bounding_box()
        assert bar and abs(bar["y"] + bar["height"] - height) <= 1, bar
        tabs = tabbar.locator(".tab")
        expect(tabs).to_have_count(4)
        for i in range(4):
            box = tabs.nth(i).bounding_box()
            assert box and box["width"] >= 44 and box["height"] >= 44, box
        plus = page.locator("#add-btn").bounding_box()
        assert plus and abs(plus["width"] - 56) <= 1 and abs(plus["height"] - 56) <= 1, plus
        assert plus["y"] >= bar["y"] and plus["y"] + plus["height"] <= bar["y"] + bar["height"], (
            plus,
            bar,
        )
        for selector, minimum in (("#menu-btn", 44), ("#period-title", 40)):
            box = page.locator(selector).bounding_box()
            assert box and box["height"] >= minimum - 1, (selector, box)
        # Giorni: today and at least the next 13 days, big rows.
        days = page.locator("#week .day")
        expect(days.first).to_have_attribute("aria-label", date.today().isoformat(), timeout=5000)
        assert days.count() >= 14
        row = page.locator("#week .event").first.bounding_box()
        assert row and row["height"] >= 48 - 1, row
        assert page.evaluate(OVERFLOW) == []
        _shot(page, f"layout_{width}_days")
        # Scrolled to the end, the last event is above the + and the tabs.
        page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        page.locator("#week").evaluate("w => w.scrollTo(0, w.scrollHeight)")
        page.wait_for_timeout(200)
        last = page.locator("#week .event").last.bounding_box()
        plus = page.locator("#add-btn").bounding_box()
        assert last and plus and last["y"] + last["height"] <= bar["y"] + 1, (last, plus)
        # Month: compact grid, and the chosen day below with its events and free time.
        _view(page, "month")
        expect(page.locator(".week.month.compact #month-scroll")).to_be_visible()
        panel = page.locator("#month-day-panel")
        expect(panel).to_be_visible()
        expect(panel.locator(".busy-name").first).to_be_visible(timeout=5000)
        assert page.evaluate(OVERFLOW) == []
        _shot(page, f"layout_{width}_month")
        _view(page, "list")
        expect(page.locator("#list-scroll .list-row").first).to_be_visible(timeout=5000)
        _shot(page, f"layout_{width}_list")
        # Calendari, Prossimi ritiri, guide, Avvisi and Turni are in the menu.
        page.locator("#menu-btn").click()
        for item in (
            "#menu-calendars",
            "#menu-pickups",
            "#menu-wizard",
            "#menu-notify",
            "#menu-shifts",
        ):
            expect(page.locator(item)).to_be_visible()
        page.locator("#menu-calendars").click()
        expect(page.locator("#filters .cal-switch").first).to_be_visible()
        _view(page, "week")


def test_events_in_the_month_and_the_day_open_their_card(stack_full: Stack, tablet: Page) -> None:
    day = date.today() if date.today().day < 25 else date.today() - timedelta(days=3)
    event = stored_event("Da cambiare", f"{day} 10:00:00", f"{day} 11:00:00", "mamma")
    stack_full.fake.events[FAMILY].append(event)
    try:
        _ready(tablet, stack_full)
        _view(tablet, "month")
        cell = tablet.locator(f".month-day[data-day='{day}']")
        line = cell.locator(".month-ev", has_text="Da cambiare")
        expect(line).to_be_visible(timeout=5000)
        line.click()
        card = tablet.locator("#card-overlay")
        expect(card).to_be_visible()
        expect(card.locator(".card-title")).to_have_text("Da cambiare")
        tablet.locator("#card-foot").get_by_role("button", name="Modifica").click()
        form = tablet.locator("#event-form")
        form.locator("input[name='summary']").fill("Cambiato")
        form.locator("button[type='submit']").click()
        expect(tablet.locator("#event-overlay")).to_be_hidden(timeout=3000)
        # Everything is read again: the month shows the new title.
        expect(cell.locator(".month-ev", has_text="Cambiato")).to_be_visible(timeout=5000)
        # The free part of the day opens the day; its appointment opens the card.
        cell.click(position={"x": 10, "y": 10})
        dayview = tablet.locator(".dayview")
        expect(dayview).to_be_visible()
        dayview.locator(".busy-name", has_text="Cambiato").click()
        expect(tablet.locator(".dayview")).to_have_count(0)
        expect(tablet.locator("#card-body .card-title")).to_have_text("Cambiato")
        tablet.locator("#card-foot").get_by_role("button", name="Chiudi").click()
        _view(tablet, "week")
    finally:
        stack_full.fake.events[FAMILY][:] = [
            e for e in stack_full.fake.events[FAMILY] if e["record_id"] != event["record_id"]
        ]


def test_a_tap_on_the_free_part_of_a_day_opens_a_new_event(stack_full: Stack, tablet: Page) -> None:
    _ready(tablet, stack_full)
    # The days are drawn again when the events arrive: wait for them, then tap by the day's name.
    expect(tablet.locator("#week .day")).to_have_count(7, timeout=5000)
    key = tablet.locator("#week .day").nth(2).get_attribute("aria-label")
    assert key
    day = tablet.locator(f"#week .day[aria-label='{key}']")
    day.click(position={"x": 40, "y": 420})
    expect(tablet.locator("#event-overlay")).to_be_visible(timeout=5000)
    expect(tablet.locator("#event-title")).to_have_text("Nuovo evento")
    expected = date.fromisoformat(key).strftime("%d/%m/%Y")
    expect(tablet.locator("#event-form input[name='date']")).to_have_value(expected)


@contextmanager
def _four_persons(stack: Stack) -> Iterator[None]:
    """Four people in the family besides the default ones: the second row must hold them all."""
    extra = [
        {"id": "papa", "name": "Papà", "role": "adult", "ha_user_id": "", "color": "#16A34A"},
        {
            "id": "cristian",
            "name": "Cristian",
            "role": "adult",
            "ha_user_id": "",
            "color": "#F59E0B",
        },
        {"id": "aurora", "name": "Aurora", "role": "child", "ha_user_id": "", "color": "#A855F7"},
    ]
    saved = []
    for state in stack.fake.states:
        if state["entity_id"].startswith("calendar.family_hub_"):
            old = copy.deepcopy(state["attributes"].get("persons", []))
            saved.append((state, old))
            state["attributes"]["persons"] = old + extra
    try:
        yield
    finally:
        for state, old in saved:
            state["attributes"]["persons"] = old


def test_second_row_keeps_every_person_whole_at_894(stack_full: Stack, browser: Browser) -> None:
    with _four_persons(stack_full), _screen(browser, 894, 727) as page:
        _ready(page, stack_full)
        chips = page.locator("#persons-bar .person-chip")
        expect(chips).to_have_count(6, timeout=5000)  # Tutti and five people
        bar = page.locator("#persons-bar").bounding_box()
        assert bar
        for i in range(6):
            box = chips.nth(i).bounding_box()
            assert (
                box
                and bar["x"] - 1 <= box["x"]
                and box["x"] + box["width"] <= bar["x"] + bar["width"] + 1
            ), (
                i,
                box,
                bar,
            )
        assert page.locator("#persons-bar").evaluate("e => e.scrollWidth <= e.clientWidth + 1")
        cal = page.locator("#calendars-btn").bounding_box()
        assert cal and cal["width"] <= 44, cal
        _shot(page, "layout_894_four_persons")


def test_a_day_shows_as_many_events_as_fit_then_how_many_are_hidden(
    stack_full: Stack, browser: Browser
) -> None:
    today = date.today()
    day = today if today.day < 25 else today - timedelta(days=3)
    added = [
        stored_event(title, f"{day} {hour:02d}:00:00", f"{day} {hour + 1:02d}:00:00", "mamma")
        for title, hour in (("Dentista", 9), ("Calcio", 17), ("Riunione", 20))
    ]
    stack_full.fake.events[FAMILY].extend(added)
    try:
        with _screen(browser, 894, 727) as page:
            _ready(page, stack_full)
            _view(page, "month")
            cell = page.locator(f".month-day[data-day='{day.isoformat()}']")
            expect(cell).to_be_visible(timeout=5000)
            expect(cell.locator(".month-ev").first).to_be_attached(timeout=5000)
            page.wait_for_timeout(200)
            shown = cell.locator(".month-ev:not([hidden])").count()
            assert shown >= 2, shown
            more = cell.locator(".month-more")
            if shown < 3:
                expect(more).to_have_text(f"+{3 - shown} altri")
            else:
                expect(more).to_be_hidden()
            fits = cell.evaluate("c => c.scrollHeight <= c.clientHeight + 1")
            assert fits
            _shot(page, "layout_894_month_day")
    finally:
        for event in added:
            stack_full.fake.events[FAMILY].remove(event)
