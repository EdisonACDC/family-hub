"""0.10.3: the top bar and the windows at 360, 390, 430, 767, 768 and 1024 px, with a family of six
persons with long names and the next pickups. Nothing is wider than the screen, "+ Nuovo" and the
menu ☰ are always there, what does not fit in the second row (Calendari, the pickups) is in the
menu, the menu scrolls when it is taller than the screen, and no window scrolls sideways.
Set FH_SCREENSHOTS to a folder to save a screenshot of each width."""

from __future__ import annotations

import copy
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_external_e2e import _add_rubbish_calendar, _remove_rubbish_calendar
from tests.fake_ha import PERSONS
from tests.helpers import ADULT_USER

WIDTHS = [360, 390, 430, 767, 768, 1024]
LONG = [
    ("p1", "Alessandra Maria"),
    ("p2", "Giovanni Battista"),
    ("p3", "Valentina Costanza"),
    ("p4", "Bartolomeo"),
    ("p5", "Ludovica Anastasia"),
    ("p6", "Francesco Saverio"),
]
RUBBISH = "calendar.family_hub_ext_ritiri"


def _shot(page: Page, name: str) -> None:
    folder = os.environ.get("FH_SCREENSHOTS")
    if folder:
        Path(folder).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(folder) / f"{name}.png"))


@contextmanager
def _big_family(stack: Stack) -> Iterator[None]:
    """Six persons with long names in every Family Hub calendar, and pickups for the week."""
    saved = {}
    persons = [
        {"id": pid, "name": name, "role": "adult", "ha_user_id": f"u-{pid}", "color": "#2563EB"}
        for pid, name in LONG
    ]
    for state in stack.fake.states:
        if (
            state["entity_id"].startswith("calendar.family_hub_")
            and "persons" in state["attributes"]
        ):
            saved[state["entity_id"]] = copy.deepcopy(state["attributes"]["persons"])
            state["attributes"]["persons"] = copy.deepcopy(PERSONS) + copy.deepcopy(persons)
    today = date.today()
    pickups = [
        {
            "summary": f"Abfuhr: {kind}",
            "start": (today + timedelta(days=n)).isoformat(),
            "end": (today + timedelta(days=n + 1)).isoformat(),
            "location": "",
            "record_id": "",
            "shift_id": "",
            "person_ids": "",
        }
        for n, kind in enumerate(("Umido", "Carta", "Plastica", "Indifferenziato"))
    ]
    _add_rubbish_calendar(stack, RUBBISH, "ritiri", pickups)
    try:
        yield
    finally:
        _remove_rubbish_calendar(stack, RUBBISH, "ritiri")
        for state in stack.fake.states:
            if state["entity_id"] in saved:
                state["attributes"]["persons"] = saved[state["entity_id"]]


@contextmanager
def _page(browser: Browser, width: int, height: int = 800) -> Iterator[Page]:
    touch = width < 1024
    context = browser.new_context(
        viewport={"width": width, "height": height}, has_touch=touch, is_mobile=width < 600
    )
    context.set_extra_http_headers({"X-Remote-User-Id": ADULT_USER})
    page = context.new_page()
    try:
        yield page
    finally:
        context.close()


def _open(page: Page, stack: Stack) -> None:
    page.goto(stack.url + "/?lang=it")
    expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
    expect(page.locator("#persons-bar .person-chip").first).to_be_visible(timeout=5000)


def _inside(page: Page, selector: str, width: int) -> bool:
    box = page.locator(selector).first.bounding_box()
    return bool(box and box["x"] >= -0.5 and box["x"] + box["width"] <= width + 0.5)


def _sideways(page: Page, width: int) -> list[str]:
    """Every visible element that sticks out of the screen on the right (outside a box that
    scrolls on purpose)."""
    return page.evaluate(
        """(width) => {
          const bad = [];
          const scrolls = (el) => {
            for (let p = el.parentElement; p; p = p.parentElement) {
              const o = getComputedStyle(p).overflowX;
              if (o === "auto" || o === "scroll" || o === "hidden") return true;
            }
            return false;
          };
          for (const el of document.querySelectorAll("body *")) {
            const r = el.getBoundingClientRect();
            if (!r.width || !r.height || getComputedStyle(el).visibility === "hidden") continue;
            if (r.right > width + 1 && !scrolls(el)) {
              bad.push((el.id || el.className || el.tagName) + " " + Math.round(r.right));
            }
          }
          return bad.slice(0, 8);
        }""",
        width,
    )


@pytest.mark.parametrize("width", WIDTHS)
def test_top_bar_fits_at_every_width(stack_full: Stack, browser: Browser, width: int) -> None:
    with _big_family(stack_full), _page(browser, width) as page:
        _open(page, stack_full)
        _shot(page, f"bar_{width}")
        # Nothing makes the page scroll sideways.
        assert page.evaluate("document.documentElement.scrollWidth") <= width, width
        # "+ Nuovo" (the + on a phone, in the bar) and the menu are always there, in the screen.
        add = "#add-btn"
        assert page.locator(add).is_visible(), width
        assert _inside(page, add, width), width
        assert page.locator("#menu-btn").is_visible() and _inside(page, "#menu-btn", width), width
        # The persons' pills scroll in their own space: they never push the others out.
        assert _inside(page, "#persons-bar", width), width
        persons = page.locator("#persons-bar").bounding_box()
        assert persons is not None
        calendars = page.locator("#calendars-btn")
        if calendars.is_visible():
            box = calendars.bounding_box()
            assert box is not None
            assert persons["x"] + persons["width"] <= box["x"] + 0.5, width  # no overlap
            assert _inside(page, "#calendars-btn", width), width
        pickups = page.locator("#pickups")
        if pickups.is_visible():
            box = pickups.bounding_box()
            assert box is not None
            assert persons["x"] + persons["width"] <= box["x"] + 0.5, width
            assert _inside(page, "#pickups", width), width
        assert _sideways(page, width) == [], width


@pytest.mark.parametrize("width", WIDTHS)
def test_what_does_not_fit_is_in_the_menu(stack_full: Stack, browser: Browser, width: int) -> None:
    """Calendari and "Prossimi ritiri" are in the menu whenever their place in the second row
    is not shown (on a phone always; on a tablet or PC when the row is too narrow)."""
    with _big_family(stack_full), _page(browser, width) as page:
        _open(page, stack_full)
        page.click("#menu-btn")
        expect(page.locator("#menu")).to_be_visible()
        calendars_in_row = page.locator("#calendars-btn").is_visible()
        pickups_in_row = page.locator("#pickups").is_visible()
        in_menu_calendars = page.locator("#menu-calendars").is_visible()
        in_menu_pickups = page.locator("#menu-pickups").is_visible()
        assert calendars_in_row != in_menu_calendars, (width, "Calendari in two places or none")
        assert pickups_in_row != in_menu_pickups, (width, "Prossimi ritiri in two places or none")
        # Under 900 px (a PC with Home Assistant's sidebar open) the second row has room for the
        # persons only; from 900 px Calendari and the pickups are in the row.
        assert in_menu_calendars == (width < 900), width
        assert in_menu_pickups == (width < 900), width
        # The menu is within the screen, and scrolls when it does not fit the height.
        assert _inside(page, "#menu", width), width
        menu = page.locator("#menu").bounding_box()
        assert menu is not None and menu["y"] + menu["height"] <= 800 + 1, width
        _shot(page, f"menu_{width}")


def test_the_menu_scrolls_on_a_short_screen(stack_full: Stack, browser: Browser) -> None:
    with _page(browser, 390, 360) as page:
        _open(page, stack_full)
        page.click("#menu-btn")
        menu = page.locator("#menu")
        expect(menu).to_be_visible()
        box = menu.bounding_box()
        assert box is not None and box["y"] + box["height"] <= 360 + 1
        assert page.evaluate("(m) => m.scrollHeight > m.clientHeight", menu.element_handle())
        assert page.evaluate("(m) => getComputedStyle(m).overflowY", menu.element_handle()) in (
            "auto",
            "scroll",
        )


# ---- the windows ------------------------------------------------------------------------------

FIND_WIDE_JS = """
(selector) => {
  const root = document.querySelector(selector);
  const dialog = root.querySelector(".dialog");
  const box = dialog.getBoundingClientRect();
  const bad = [];
  if (box.right > window.innerWidth + 1 || box.left < -1) bad.push("dialog outside the screen");
  if (dialog.scrollWidth > dialog.clientWidth + 1) bad.push("dialog scrolls sideways");
  for (const body of dialog.querySelectorAll(".dialog-body")) {
    if (body.scrollWidth > body.clientWidth + 1) {
      bad.push("body scrolls sideways " + body.scrollWidth + ">" + body.clientWidth);
    }
  }
  const scrolls = (el) => {
    for (let p = el.parentElement; p && p !== dialog; p = p.parentElement) {
      const o = getComputedStyle(p).overflowX;
      if (o === "auto" || o === "scroll") return true;
    }
    return false;
  };
  for (const el of dialog.querySelectorAll("*")) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || getComputedStyle(el).visibility === "hidden") continue;
    if (el.closest("[hidden]")) continue;
    if ((r.right > box.right + 1 || r.left < box.left - 1) && !scrolls(el)) {
      const name = el.id || el.className || el.tagName;
      bad.push(name + " " + Math.round(r.left) + ".." + Math.round(r.right));
    }
  }
  return bad.slice(0, 8);
}
"""

LONG_NAME = "Nonna Alessandra Maria di Castelvecchio con un nome molto lungo"
DEVICE = {
    "id": "c" * 32,
    "name": LONG_NAME,
    "label": "Android · Chrome",
    "activated_at": "2026-11-14T10:00:00+00:00",
    "last_seen": "2026-11-15T08:00:00+00:00",
    "status": "active",
    "persons": ["sofia", "mamma"],
    "categories": ["famiglia"],
    "permission": "edit_own",
    "approval": "approve",
    "notify": True,
    "push": False,
    "family_events": False,
    "has_shifts": True,
    "shifts_person": "",
    "person_id": "guest_x",
    "template": "grandparents",
    "mode": "full",
    "features": {
        "calendar": True,
        "reminders": True,
        "lists": True,
        "waste": True,
        "weather": True,
    },
    "lists": [],
    "lists_edit": False,
    "externals": [],
}


def _fits(page: Page, overlay: str, where: str) -> None:
    wide = page.evaluate(FIND_WIDE_JS, overlay)
    assert wide == [], f"{where}: {wide}"


def _menu_item(page: Page, item: str) -> None:
    page.click("#menu-btn")
    page.click(f"#{item}")


@pytest.mark.parametrize("width", [360, 390, 430, 768, 1024])
def test_the_windows_fit_the_width(stack_full: Stack, browser: Browser, width: int) -> None:
    stack_full.fake.guest["devices"] = [dict(DEVICE)]
    stack_full.fake.guest["invites"] = []
    try:
        with _big_family(stack_full), _page(browser, width, 700) as page:
            _open(page, stack_full)
            errors: list[str] = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            # Condivisione: the new invite (long labels, switches), the devices, the permissions.
            _menu_item(page, "menu-share")
            expect(page.locator("#share-overlay")).to_be_visible()
            page.locator("#share-new [data-feature='lists']").scroll_into_view_if_needed()
            _fits(page, "#share-overlay", f"share new invite {width}")
            _shot(page, f"share_{width}")
            page.click("#share-tab-devices")
            _fits(page, "#share-overlay", f"share devices {width}")
            card = page.locator(f"[data-device='{DEVICE['id']}']")
            card.get_by_role("button", name="Modifica permessi").click()
            expect(card.locator(".share-edit")).to_be_visible()
            _fits(page, "#share-overlay", f"share permissions {width}")
            _shot(page, f"permissions_{width}")
            page.click("#share-close")
            # Avvisi, Turni, Calendari esterni.
            for item, overlay, close, name in (
                ("menu-notify", "#notify-overlay", "#notify-close", "avvisi"),
                ("menu-shifts", "#shifts-overlay", "#shifts-close", "turni"),
                ("menu-ics", "#ics-overlay", "#ics-close", "calendari esterni"),
            ):
                _menu_item(page, item)
                expect(page.locator(overlay)).to_be_visible()
                page.wait_for_timeout(300)
                _fits(page, overlay, f"{name} {width}")
                _shot(page, f"{name.replace(' ', '_')}_{width}")
                page.click(close)
            # Procedura guidata: every step.
            _menu_item(page, "menu-wizard")
            expect(page.locator("#wizard-overlay")).to_be_visible()
            for step in range(6):
                page.wait_for_timeout(150)
                _fits(page, "#wizard-overlay", f"guide step {step + 1} at {width}")
                if step == 0:
                    _shot(page, f"wizard_{width}")
                if step < 5:
                    page.click("#wizard-skip")
            assert errors == []
    finally:
        stack_full.fake.guest["devices"] = []
