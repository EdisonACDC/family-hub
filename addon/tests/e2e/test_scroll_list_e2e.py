"""0.6.5: months one under the other (loaded while scrolling, title fixed at the top, "Oggi",
arrows, keyboard and wheel), swiping the week, and the list view with its filters."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta

from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_tablet import _shot
from tests.fake_ha import FAMILY, SCHOOL, WASTE, stored_event
from tests.helpers import ADULT_USER


def _month_key(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def _add_months(d: date, n: int) -> date:
    month = d.month - 1 + n
    return date(d.year + month // 12, month % 12 + 1, 1)


def _block_offset(page: Page, key: str) -> float:
    """How far the month's block is from the top of the scroller (0: at the top)."""
    return float(
        page.evaluate(
            """key => {
              const s = document.getElementById('month-scroll');
              const b = s.querySelector(`.month-block[data-month='${key}']`);
              return b.getBoundingClientRect().top - s.getBoundingClientRect().top;
            }""",
            key,
        )
    )


def _open_month(page: Page, stack: Stack) -> None:
    page.goto(stack.url + "/?lang=it")
    expect(page.locator(".chip").first).to_be_visible(timeout=5000)
    page.locator("#view-switch [data-view='month']").click()
    expect(page.locator("#month-scroll")).to_be_visible(timeout=5000)


def test_months_scroll_load_and_keep_their_title_at_the_top(
    stack_full: Stack, tablet: Page
) -> None:
    today = date.today()
    later = _add_months(today, 5).replace(day=10)
    event = stored_event("Lontano", f"{later} 09:00:00", f"{later} 11:00:00")
    stack_full.fake.events[FAMILY].append(event)
    try:
        _open_month(tablet, stack_full)
        blocks = tablet.locator(".month-block")
        assert blocks.count() >= 16
        now_key = _month_key(today)
        expect(tablet.locator(f".month-block[data-month='{now_key}']")).to_have_class(
            "month-block loaded", timeout=5000
        )
        assert abs(_block_offset(tablet, now_key)) < 3
        # Far months are not read until they come near.
        far_key = _month_key(_add_months(today, 11))
        expect(tablet.locator(f".month-block[data-month='{far_key}']")).not_to_have_class(
            "month-block loaded"
        )
        _shot(tablet, "tablet_month_scroll")

        # Scroll to the month five ahead: it is read, and its event counts.
        later_key = _month_key(later)
        tablet.evaluate(
            """key => {
              const s = document.getElementById('month-scroll');
              const b = s.querySelector(`.month-block[data-month='${key}']`);
              s.scrollTop = b.offsetTop - s.offsetTop + 200;
            }""",
            later_key,
        )
        cell = tablet.locator(f".month-day[data-day='{later}']")
        expect(cell).to_have_attribute("data-busy", "120", timeout=5000)
        # The block's title stays at the top while its days scroll under it.
        title = tablet.locator(f".month-block[data-month='{later_key}'] .month-title")
        scroller_top = tablet.locator("#month-scroll").bounding_box()["y"]  # type: ignore[index]
        assert abs(title.bounding_box()["y"] - scroller_top) < 3  # type: ignore[index]

        # "Oggi" goes back to this month.
        tablet.locator("#this-week").click()
        tablet.wait_for_function(
            """key => {
              const s = document.getElementById('month-scroll');
              const b = s.querySelector(`.month-block[data-month='${key}']`);
              return Math.abs(b.getBoundingClientRect().top - s.getBoundingClientRect().top) < 3;
            }""",
            arg=now_key,
            timeout=5000,
        )
        # The arrow jumps one month; PageDown on the keyboard too; the wheel scrolls.
        tablet.locator("#next-week").click()
        next_key = _month_key(_add_months(today, 1))
        assert abs(_block_offset(tablet, next_key)) < 3
        tablet.locator("#month-scroll").focus()
        tablet.keyboard.press("PageDown")
        assert abs(_block_offset(tablet, _month_key(_add_months(today, 2)))) < 3
        before = tablet.evaluate("document.getElementById('month-scroll').scrollTop")
        box = tablet.locator("#month-scroll").bounding_box()
        assert box
        tablet.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        tablet.mouse.wheel(0, 400)
        tablet.wait_for_function(
            "before => document.getElementById('month-scroll').scrollTop > before", arg=before
        )
        tablet.locator("#view-switch [data-view='week']").click()
    finally:
        stack_full.fake.events[FAMILY].remove(event)


def _swipe(page: Page, from_x: int, to_x: int, y: int = 450) -> None:
    page.evaluate(
        """([fromX, toX, y]) => {
          const w = document.getElementById('week');
          const opts = (x) => ({ clientX: x, clientY: y, pointerType: 'touch', bubbles: true });
          w.dispatchEvent(new PointerEvent('pointerdown', opts(fromX)));
          w.dispatchEvent(new PointerEvent('pointerup', opts(toX)));
        }""",
        [from_x, to_x, y],
    )


def test_swiping_the_week_goes_to_the_next_and_previous_week(
    stack_full: Stack, tablet: Page
) -> None:
    tablet.goto(stack_full.url + "/?lang=it")
    expect(tablet.locator(".chip").first).to_be_visible(timeout=5000)
    today = date.today()
    first = tablet.locator("#week .day").first
    expect(first).to_have_attribute("aria-label", today.isoformat(), timeout=5000)
    _swipe(tablet, 700, 300)
    expect(first).to_have_attribute("aria-label", (today + timedelta(days=7)).isoformat())
    _swipe(tablet, 300, 700)
    expect(first).to_have_attribute("aria-label", today.isoformat())
    # A vertical move is not a swipe.
    tablet.evaluate(
        """() => {
          const w = document.getElementById('week');
          const o = (y) => ({ clientX: 500, clientY: y, pointerType: 'touch', bubbles: true });
          w.dispatchEvent(new PointerEvent('pointerdown', o(200)));
          w.dispatchEvent(new PointerEvent('pointerup', o(600)));
        }"""
    )
    expect(first).to_have_attribute("aria-label", today.isoformat())


def test_swiping_on_the_phone_moves_one_day(stack_full: Stack, browser: Browser) -> None:
    context = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True)
    context.set_extra_http_headers({"X-Remote-User-Id": ADULT_USER})
    page = context.new_page()
    try:
        page.goto(stack_full.url + "/?lang=it")
        expect(page.locator(".chip").first).to_be_visible(timeout=5000)
        first = page.locator("#week .day").first
        today = date.today()
        expect(first).to_have_attribute("aria-label", today.isoformat(), timeout=5000)
        _swipe(page, 330, 40, 600)
        expect(first).to_have_attribute("aria-label", (today + timedelta(days=1)).isoformat())
    finally:
        context.close()


@contextmanager
def _list_events(stack: Stack) -> Iterator[None]:
    fake = stack.fake
    today = date.today()
    d1, d2, d3 = today + timedelta(days=3), today + timedelta(days=40), today + timedelta(days=2)
    family = stored_event("Lista Mamma", f"{d1} 18:00:00", f"{d1} 19:00:00", "mamma")
    school = stored_event("Lista Sofia", f"{d2} 08:00:00", f"{d2} 13:00:00", "sofia")
    styles = fake.config["sources"].setdefault("calendar_styles", {})
    styles[WASTE] = {"name": "Rifiuti", "type": "rifiuti", "color": "#64748B", "persons": []}
    waste_before = list(fake.events.get(WASTE, []))
    fake.events[WASTE] = [
        stored_event("Abfuhr: Bioabfall", d3.isoformat(), (d3 + timedelta(1)).isoformat())
    ]
    fake.events[FAMILY].append(family)
    fake.events[SCHOOL].append(school)
    try:
        yield
    finally:
        fake.events[FAMILY].remove(family)
        fake.events[SCHOOL].remove(school)
        fake.events[WASTE] = waste_before
        styles.pop(WASTE, None)


def test_list_view_shows_the_year_by_month_and_day_with_filters(
    stack_full: Stack, tablet: Page
) -> None:
    with _list_events(stack_full):
        tablet.goto(stack_full.url + "/?lang=it")
        expect(tablet.locator(".chip").first).to_be_visible(timeout=5000)
        tablet.locator("#view-switch [data-view='list']").click()
        body = tablet.locator("#list-scroll")
        expect(body.locator(".list-row", has_text="Lista Mamma")).to_be_visible(timeout=5000)
        expect(body.locator(".list-row", has_text="Lista Sofia")).to_be_attached()
        expect(body.locator(".list-month").first).to_be_visible()
        row = body.locator(".list-row", has_text="Lista Mamma")
        expect(row.locator(".list-time")).to_have_text("18:00")
        expect(row.locator(".list-persons")).to_have_text("Mamma")
        # Rubbish only when asked for.
        expect(body.locator(".list-row", has_text="Organico")).to_have_count(0)
        tablet.locator(".week.list-view label", has_text="Mostra rifiuti").click()
        expect(tablet.locator("#list-scroll .list-row", has_text="Organico")).to_be_visible()
        _shot(tablet, "tablet_list_view")
        # The person filter, as in the month view.
        tablet.locator("#month-person").select_option("sofia")
        expect(tablet.locator("#list-scroll .list-row", has_text="Lista Mamma")).to_have_count(0)
        sofia = tablet.locator("#list-scroll .list-row", has_text="Lista Sofia")
        expect(sofia).to_be_visible()
        sofia.click()
        expect(tablet.locator("#card-body .card-title")).to_have_text("Lista Sofia")
        tablet.locator("#card-foot").get_by_role("button", name="Chiudi").click()
        tablet.locator("#month-person").select_option("")
        tablet.locator("#view-switch [data-view='week']").click()


def test_list_and_month_on_the_phone(stack_full: Stack, browser: Browser) -> None:
    context = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True)
    context.set_extra_http_headers({"X-Remote-User-Id": ADULT_USER})
    page = context.new_page()
    try:
        with _list_events(stack_full):
            page.goto(stack_full.url + "/?lang=it")
            expect(page.locator(".chip").first).to_be_visible(timeout=5000)
            page.locator("#view-switch [data-view='list']").click()
            expect(page.locator("#list-scroll .list-row", has_text="Lista Mamma")).to_be_visible(
                timeout=5000
            )
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            _shot(page, "phone_list_view")
            page.locator("#view-switch [data-view='month']").click()
            expect(page.locator(".week.month.compact #month-scroll")).to_be_visible()
            # The months scroll inside their area, which opens on this month.
            now_key = _month_key(date.today())
            expect(page.locator(f".month-block[data-month='{now_key}']")).to_have_class(
                "month-block loaded", timeout=5000
            )
            assert abs(_block_offset(page, now_key)) < 3
            # The three views fit: short names on the phone.
            expect(page.locator("#view-switch [data-view='week'] .label-short")).to_have_text(
                "Sett."
            )
            names = page.locator("#view-switch .segment").evaluate_all(
                "bs => bs.map(b => b.scrollWidth <= b.clientWidth + 1)"
            )
            assert all(names), names
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            _shot(page, "phone_month_scroll")
            page.locator("#view-switch [data-view='week']").click()
    finally:
        context.close()
