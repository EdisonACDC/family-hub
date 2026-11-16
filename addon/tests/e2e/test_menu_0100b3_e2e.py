"""0.10.0b3: the menu closes with a tap outside, with Esc, when the view changes and when an
event or "+ Nuovo" opens. (The guests' web app in "Completa" uses this same menu.)"""

from __future__ import annotations

from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack, tablet_as
from tests.helpers import ADULT_USER


def _open_menu(page: Page) -> None:
    page.click("#menu-btn")
    expect(page.locator("#menu")).to_be_visible()
    expect(page.locator("#menu-btn")).to_have_attribute("aria-expanded", "true")


def _closed(page: Page) -> None:
    expect(page.locator("#menu")).to_be_hidden()
    expect(page.locator("#menu-btn")).to_have_attribute("aria-expanded", "false")


def test_menu_closes(stack_full: Stack, browser: Browser) -> None:
    with tablet_as(browser, ADULT_USER) as page:
        errors: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto(stack_full.url + "/?lang=it")
        expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
        # A tap outside.
        _open_menu(page)
        page.click("#clock-time")
        _closed(page)
        # Esc.
        _open_menu(page)
        page.keyboard.press("Escape")
        _closed(page)
        # A tap inside the menu keeps it open (the switch works); the button closes it.
        _open_menu(page)
        page.locator("#menu .menu-switch").click()
        expect(page.locator("#menu")).to_be_visible()
        page.locator("#menu .menu-switch").click()
        page.click("#menu-btn")
        _closed(page)
        # Changing the view.
        for view in ("month", "list", "week"):
            _open_menu(page)
            page.click(f"#view-switch [data-view='{view}']")
            _closed(page)
            expect(page.locator(f"#view-switch [data-view='{view}']")).to_have_attribute(
                "aria-pressed", "true"
            )
        # "+ Nuovo".
        _open_menu(page)
        page.click("#add-btn")
        expect(page.locator("#event-overlay")).to_be_visible()
        _closed(page)
        page.click("#event-cancel")
        assert errors == []
