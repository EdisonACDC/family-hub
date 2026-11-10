"""0.7.7b4: rubbish pickups made by hand. The dialog fits a 320 px phone; a schedule is sent as the
family made it; a schedule that cannot be used says why and stays open."""

from __future__ import annotations

from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_layout_071_e2e import _open
from tests.e2e.test_tablet import _device


def _open_manual(page: Page) -> None:
    page.locator("#menu-btn").click()
    page.locator("#menu-ics").click()
    page.locator("#ics-manual-open").click()
    expect(page.locator("#manual-overlay")).to_be_visible(timeout=3000)


def _organico_card(page: Page):  # type: ignore[no-untyped-def]
    return page.locator("#manual-body fieldset", has_text="Organico")


def test_the_pickups_dialog_fits_a_320_px_phone(stack_full: Stack, browser: Browser) -> None:
    stack_full.fake.manual = {"rules": [], "extra": [], "skip": [], "moves": []}
    with _device(browser, 320, 640) as page:
        _open(page, stack_full)
        _open_manual(page)
        box = page.locator("#manual-overlay .dialog").bounding_box()
        assert box is not None
        assert box["x"] >= 0 and box["x"] + box["width"] <= 321, box
        assert box["y"] >= 0 and box["y"] + box["height"] <= 641, box


def test_a_schedule_is_sent_as_the_family_made_it(stack_full: Stack, browser: Browser) -> None:
    stack_full.fake.manual = {"rules": [], "extra": [], "skip": [], "moves": []}
    before = len(stack_full.fake.saved_manual)
    with _device(browser, 390, 844) as page:
        _open(page, stack_full)
        _open_manual(page)
        card = _organico_card(page)
        card.get_by_label("C'è un ritiro").check()
        card.locator("select").first.select_option("biweekly")
        card.locator("input[type='date']").first.fill("2026-11-03")
        page.locator("#manual-save").click()
        expect(page.locator("#manual-overlay")).to_be_hidden(timeout=3000)
    saved = stack_full.fake.saved_manual[before:]
    assert len(saved) == 1
    assert saved[0]["rules"] == [
        {"type": "bio", "frequency": "biweekly", "weekday": "tue", "first": "2026-11-03"}
    ]


def test_a_schedule_that_cannot_be_used_says_why_and_stays_open(
    stack_full: Stack, browser: Browser
) -> None:
    stack_full.fake.manual = {"rules": [], "extra": [], "skip": [], "moves": []}
    with _device(browser, 390, 844) as page:
        _open(page, stack_full)
        _open_manual(page)
        card = _organico_card(page)
        card.get_by_label("C'è un ritiro").check()
        # 4 November is a Wednesday: not the weekday a pickup needs for this rule.
        card.locator("input[type='date']").first.fill("2026-11-04")
        page.locator("#manual-save").click()
        expect(page.locator("#manual-error")).to_contain_text("Il primo ritiro non cade")
        expect(page.locator("#manual-overlay")).to_be_visible()
