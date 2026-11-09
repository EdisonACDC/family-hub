"""0.7.1 layout matrix: every screen at 320, 360, 390, 430, 768 and 1024 px wide.

For each screen the checks are:
- no horizontal scroll of the page;
- the buttons at the foot of the open window are fully on screen and the one touched in the middle
  of each is the button itself (not the bottom bar, not the + button);
- the period title is not cut;
- no visible button smaller than 40 px.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, timedelta

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_tablet import _device, _push
from tests.fake_ha import FAMILY, WASTE, stored_event

SIZES = [(320, 640), (360, 780), (390, 844), (430, 932), (768, 1024), (1024, 768)]

CHECK_JS = """() => {
  const bad = [];
  const hscroll = document.documentElement.scrollWidth - window.innerWidth;
  if (hscroll > 1) bad.push(['hscroll', hscroll]);
  const title = document.getElementById('period-title');
  if (title && title.offsetParent && title.scrollWidth > title.clientWidth + 1) {
    bad.push(['title-cut', title.textContent.trim()]);
  }
  const overlays = [...document.querySelectorAll('.overlay:not([hidden])')];
  const top = overlays[overlays.length - 1];
  if (top) {
    top.querySelectorAll('.dialog-foot button').forEach(b => {
      if (!b.offsetParent || b.disabled) return;
      const r = b.getBoundingClientRect();
      const name = b.textContent.trim();
      if (r.left < -1 || r.right > innerWidth + 1 || r.bottom > innerHeight + 1 || r.top < -1) {
        const box = [Math.round(r.left), Math.round(r.right), Math.round(r.bottom)];
        bad.push(['foot-outside', name, ...box]);
        return;
      }
      const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      if (!hit || !(hit === b || b.contains(hit))) {
        bad.push(['foot-covered', name, hit ? (hit.id || hit.className || hit.tagName) : 'none']);
      }
    });
  }
  // Everything inside the open window (inputs, buttons, calendar days) stays within its left and
  // right edges; a list may scroll up and down inside the window, but not sideways.
  const win = top ? top.querySelector('.dialog') : null;
  if (win) {
    const d = win.getBoundingClientRect();
    win.querySelectorAll('input, select, textarea, button, .day-cell').forEach(e => {
      if (!e.offsetParent || e.disabled) return;
      const r = e.getBoundingClientRect();
      if (r.width === 0) return;
      if (r.left < d.left - 1 || r.right > d.right + 1) {
        const label = (e.id || e.getAttribute('aria-label') || e.textContent || e.tagName).trim();
        bad.push(['outside-window', label.slice(0, 24),
          Math.round(r.left), Math.round(r.right), Math.round(d.left), Math.round(d.right)]);
      }
    });
  }
  document.querySelectorAll('button').forEach(b => {
    if (!b.offsetParent || b.disabled) return;
    if (b.closest('.month-day, .month-top, .free-slot, .busy-name, .cal-switch, .list-row')) return;
    const r = b.getBoundingClientRect();
    if (r.width === 0) return;
    // A calendar day is as narrow as seven columns of the window allow; it keeps a 40 px height.
    const narrowDay = b.classList.contains('day-cell');
    if (r.height < 40 || (!narrowDay && r.width < 40)) {
      bad.push([
        'small', b.textContent.trim().slice(0, 20), Math.round(r.width), Math.round(r.height)
      ]);
    }
  });
  return bad;
}"""


@contextmanager
def _seeded(stack: Stack) -> Iterator[None]:
    """A day with appointments, and a day with a long title, so the screens are not empty."""
    today = date.today()
    added = [
        stored_event(
            "Dentista Sofia con visita di controllo",
            f"{today} 09:00:00",
            f"{today} 10:00:00",
            "mamma",
        ),
        stored_event("Calcio", f"{today} 17:00:00", f"{today} 18:30:00", "sofia"),
        stored_event(
            "Riunione di famiglia",
            f"{today + timedelta(days=2)} 20:00:00",
            f"{today + timedelta(days=2)} 21:00:00",
            "mamma",
        ),
    ]
    pickup = stored_event(
        "Abfuhr: Bioabfall", f"{today + timedelta(days=1)}", f"{today + timedelta(days=2)}"
    )
    stack.fake.events[FAMILY].extend(added)
    stack.fake.events[WASTE].append(pickup)
    styles = stack.fake.config["sources"].setdefault("calendar_styles", {})
    styles[WASTE] = {"name": "Rifiuti", "type": "rifiuti", "color": "#64748B", "persons": []}
    try:
        yield
    finally:
        for event in added:
            stack.fake.events[FAMILY].remove(event)
        stack.fake.events[WASTE].remove(pickup)
        styles.pop(WASTE, None)


def _open(page: Page, stack: Stack) -> None:
    # Every screen starts from the Giorni view with no person chosen (as a new visit does).
    page.add_init_script(
        "try { localStorage.removeItem('fh_view'); localStorage.removeItem('fh_person'); }"
        " catch (e) {}"
    )
    page.goto(stack.url + "/?lang=it")
    expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=8000)


def _phone(page: Page) -> bool:
    return (page.viewport_size or {}).get("width", 1024) < 600


def _menu(page: Page, item: str) -> None:
    page.locator("#menu-btn").click()
    page.locator(item).click()


def _menu_lists(page: Page) -> None:
    if _phone(page):
        page.locator("#tabbar [data-tab='lists']").click()
    else:
        page.locator("#todo-btn").click()


def _view(page: Page, view: str) -> None:
    if _phone(page):
        page.locator(f"#tabbar [data-tab='{view}']").click()
    else:
        page.locator(f"#view-switch [data-view='{view}']").click()


def _screens(stack: Stack) -> list[tuple[str, Callable[[Page], None]]]:
    def giorni(page: Page) -> None:
        expect(page.locator("#week .day").first).to_be_visible(timeout=5000)

    def mese(page: Page) -> None:
        _view(page, "month")
        expect(page.locator("#month-scroll")).to_be_visible(timeout=5000)

    def giornata(page: Page) -> None:
        _view(page, "month")
        cell = page.locator(".month-day").nth(10)
        expect(cell).to_be_visible(timeout=5000)
        if _phone(page):
            cell.click(position={"x": 4, "y": 4})  # the day below the month (phone)
        else:
            cell.click(position={"x": 4, "y": 4})  # the day in a window (tablet)
            expect(page.locator(".day-overlay")).to_be_visible(timeout=3000)

    def elenco(page: Page) -> None:
        _view(page, "list")
        expect(page.locator("#list-scroll")).to_be_visible(timeout=5000)

    def liste(page: Page) -> None:
        if _phone(page):
            page.locator("#tabbar [data-tab='lists']").click()
        else:
            page.locator("#todo-btn").click()
        expect(page.locator("#todo-overlay")).to_be_visible(timeout=3000)

    def menu(page: Page) -> None:
        page.locator("#menu-btn").click()
        expect(page.locator("#menu")).to_be_visible()

    def avvisi(page: Page) -> None:
        _menu(page, "#menu-notify")
        expect(page.locator("#notify-overlay")).to_be_visible(timeout=3000)

    def turni_modelli(page: Page) -> None:
        _menu(page, "#menu-shifts")
        expect(page.locator("#shifts-overlay")).to_be_visible(timeout=3000)

    def turni_calendario(page: Page) -> None:
        turni_modelli(page)
        page.locator("#tab-calendar").click()
        expect(page.locator("#shifts-calendar")).to_be_visible(timeout=3000)

    def esterni(page: Page) -> None:
        _menu(page, "#menu-ics")
        expect(page.locator("#ics-overlay")).to_be_visible(timeout=3000)

    def ritiri(page: Page) -> None:
        if _phone(page):
            _menu(page, "#menu-pickups")
            expect(page.locator("#pickups-overlay")).to_be_visible(timeout=3000)
        else:
            expect(page.locator("#pickups .pickup-chip").first).to_be_visible(timeout=5000)

    def calendari(page: Page) -> None:
        if _phone(page):
            _menu(page, "#menu-calendars")
        else:
            page.locator("#calendars-btn").click()
        expect(page.locator("#filters")).to_be_visible(timeout=3000)

    def nuovo_in_alto(page: Page) -> None:
        page.locator("#add-btn").click()
        expect(page.locator("#event-overlay")).to_be_visible(timeout=3000)

    def nuovo_in_fondo(page: Page) -> None:
        nuovo_in_alto(page)
        page.locator("#event-form .dialog-body").evaluate("e => e.scrollTop = e.scrollHeight")

    def selettore_ora(page: Page) -> None:
        nuovo_in_alto(page)
        page.locator("#event-form input[name='start_time']").click()
        expect(page.locator(".timepick")).to_be_visible(timeout=3000)

    def scheda_evento(page: Page) -> None:
        page.locator(".event", has_text="Calcio").first.click()
        expect(page.locator("#card-overlay")).to_be_visible(timeout=3000)

    def promemoria(page: Page) -> None:
        _push(
            stack,
            "family_hub_reminder",
            {"uid": "rem-layout", "title": "Promemoria", "message": "15:00 · Dentista Sofia"},
        )
        expect(page.locator("#reminder-overlay")).to_be_visible(timeout=3000)

    def wizard(step: int) -> Callable[[Page], None]:
        def run(page: Page) -> None:
            _menu(page, "#menu-wizard")
            expect(page.locator("#wizard-overlay")).to_be_visible(timeout=3000)
            for _ in range(step - 1):
                page.locator("#wizard-next").click()
            expect(page.locator("#wizard-progress")).to_have_text(
                f"Passo {step} di 6", timeout=3000
            )

        return run

    screens: list[tuple[str, Callable[[Page], None]]] = [
        ("giorni", giorni),
        ("mese", mese),
        ("giornata", giornata),
        ("elenco", elenco),
        ("liste", liste),
        ("menu", menu),
        ("avvisi", avvisi),
        ("turni-modelli", turni_modelli),
        ("turni-calendario", turni_calendario),
        ("calendari-esterni", esterni),
        ("prossimi-ritiri", ritiri),
        ("calendari", calendari),
        ("nuovo-in-alto", nuovo_in_alto),
        ("nuovo-in-fondo", nuovo_in_fondo),
        ("selettore-ora", selettore_ora),
        ("scheda-evento", scheda_evento),
        ("promemoria", promemoria),
    ]
    screens += [(f"wizard-passo-{n}", wizard(n)) for n in range(1, 7)]
    return screens


@pytest.mark.parametrize(("width", "height"), SIZES)
def test_every_screen_fits_and_its_buttons_are_reachable(
    stack_full: Stack, browser: Browser, width: int, height: int
) -> None:
    problems: list[str] = []
    with _seeded(stack_full), _device(browser, width, height) as page:
        for name, go in _screens(stack_full):
            _open(page, stack_full)
            try:
                go(page)
                page.wait_for_timeout(150)
                for item in page.evaluate(CHECK_JS):
                    problems.append(f"{name}: {item}")
            except Exception as err:  # the screen could not be reached at this size
                problems.append(f"{name}: could not open ({type(err).__name__}: {str(err)[:120]})")
    assert not problems, f"at {width}x{height}:\n" + "\n".join(problems)


@pytest.mark.parametrize(("width", "height"), [(320, 640), (390, 844)])
def test_lists_entry_line_fits_and_adds_an_item(
    stack_full: Stack, browser: Browser, width: int, height: int
) -> None:
    """0.7.3: the entry line of a list is inside the window, and Aggiungi really adds the entry."""
    with _device(browser, width, height) as page:
        _open(page, stack_full)
        _menu_lists(page)
        overlay = page.locator("#todo-overlay")
        expect(overlay).to_be_visible(timeout=3000)
        entry = overlay.locator(".todo-add")
        expect(entry).to_be_visible(timeout=5000)
        entry.locator("input").fill("Latte di prova")
        entry.locator("button[type='submit']").click()
        expect(overlay.get_by_text("Latte di prova", exact=True)).to_be_visible(timeout=5000)
        problems = page.evaluate(CHECK_JS)
        assert not problems, f"at {width}x{height}: {problems}"


def test_shift_calendar_last_day_is_reachable_at_320(stack_full: Stack, browser: Browser) -> None:
    """0.7.3: at 320 px the days of the month fit the window sideways; the last one can be scrolled
    to and tapped."""
    with _device(browser, 320, 640) as page:
        _open(page, stack_full)
        _menu(page, "#menu-shifts")
        expect(page.locator("#shifts-overlay")).to_be_visible(timeout=3000)
        page.locator("#tab-calendar").click()
        cells = page.locator("#shifts-calendar .day-cell")
        expect(cells.first).to_be_visible(timeout=3000)
        last = cells.last
        last.scroll_into_view_if_needed()
        box = last.bounding_box()
        assert box is not None
        hit = page.evaluate(
            "([x, y]) => { const e = document.elementFromPoint(x, y);"
            " return e ? e.closest('.day-cell') !== null : false; }",
            [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2],
        )
        assert hit, "the last day is covered by something else"
        problems = page.evaluate(CHECK_JS)
        assert not problems, problems
