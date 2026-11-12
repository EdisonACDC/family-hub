"""0.8.0b3: the pickups made by hand are in the panel's list, and once saved they show in the month,
the week and "Prossimi ritiri", as a file's pickups do."""

from __future__ import annotations

import re
from datetime import date, timedelta

from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_layout_071_e2e import _open, _view
from tests.e2e.test_tablet import _device


def _pickup_day() -> str:
    """The Tuesday of the week shown from today: the pickup is in that week and this month.
    The test fake takes the pickups of Tuesdays only. Near a month's end, the Tuesday before."""
    today = date.today()
    forward = today + timedelta(days=(1 - today.weekday()) % 7)
    if forward.month == today.month:
        return forward.isoformat()
    return (today - timedelta(days=(today.weekday() - 1) % 7)).isoformat()


def _create_organico(page: Page, day: str) -> None:
    page.locator("#menu-btn").click()
    page.locator("#menu-ics").click()
    expect(page.locator("#ics-overlay")).to_be_visible(timeout=3000)
    page.locator("#ics-manual-open").click()
    manual = page.locator("#manual-overlay")
    expect(manual).to_be_visible(timeout=3000)
    card = page.locator("#manual-body fieldset", has_text="Organico")
    card.get_by_label("C'è un ritiro").check()
    card.locator("select").first.select_option("biweekly")
    card.locator("input[type='date']").first.fill(day)
    page.locator("#manual-save").click()
    expect(manual).to_be_hidden(timeout=3000)
    page.locator("#ics-close").click()
    expect(page.locator("#ics-overlay")).to_be_hidden(timeout=3000)


def test_pickups_made_by_hand_show_in_the_month_week_and_next_pickups(
    stack_full: Stack, browser: Browser
) -> None:
    stack_full.fake.manual = {"rules": [], "extra": [], "skip": [], "moves": []}
    try:
        with _device(browser, 1024, 768) as page:
            _open(page, stack_full)
            _create_organico(page, _pickup_day())
            # The new calendar is in the list (refreshed after the save).
            expect(page.locator("#filters")).to_contain_text("Ritiri a mano", timeout=6000)
            # The month: the pickup is written on its day.
            _view(page, "month")
            expect(page.locator("#week")).to_contain_text("Organico", timeout=6000)
            # The week shown from today: the pickup is in it.
            _view(page, "week")
            expect(page.locator("#week")).to_contain_text("Organico", timeout=6000)
            # "Prossimi ritiri" lists it (the phone shows it in the menu).
            page.set_viewport_size({"width": 390, "height": 844})
            page.locator("#menu-btn").click()
            page.locator("#menu-pickups").click()
            expect(page.locator("#pickups-list .pickup-chip", has_text="Organico")).to_have_count(
                1, timeout=6000
            )
            page.locator("#pickups-close").click()
    finally:
        stack_full.fake.manual = {"rules": [], "extra": [], "skip": [], "moves": []}
        stack_full.fake.events.pop("calendar.family_hub_ext_manualwaste", None)


def test_modifica_on_the_pickups_opens_them_over_the_list_and_closing_returns_to_it(
    stack_full: Stack, browser: Browser
) -> None:
    stack_full.fake.manual = {
        "rules": [
            {"type": "bio", "frequency": "biweekly", "weekday": "tue", "first": "2026-11-17"}
        ],
        "extra": [],
        "skip": [],
        "moves": [],
    }
    try:
        with _device(browser, 390, 844) as page:
            _open(page, stack_full)
            page.locator("#menu-btn").click()
            page.locator("#menu-ics").click()
            card = page.locator("#ics-body .ics-card", has_text="Ritiri a mano")
            expect(card).to_be_visible(timeout=5000)
            card.get_by_role("button", name=re.compile("Modifica|Bearbeiten|Edit")).click()
            expect(page.locator("#manual-overlay")).to_be_visible(timeout=3000)
            # Closing the pickups returns to the list, still open.
            page.locator("#manual-cancel").click()
            expect(page.locator("#manual-overlay")).to_be_hidden()
            expect(page.locator("#ics-overlay")).to_be_visible()
    finally:
        stack_full.fake.manual = {"rules": [], "extra": [], "skip": [], "moves": []}
        stack_full.fake.events.pop("calendar.family_hub_ext_manualwaste", None)
