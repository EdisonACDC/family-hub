"""0.9.0b1 small fixes: each step of the guide starts from the top, and step 5 in Italian speaks of
the region (German keeps "Land")."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from tests.e2e.conftest import Stack


def _guide(page: Page, stack: Stack, lang: str) -> None:
    stack.fake.config["configured"] = False  # the guide opens by itself
    page.goto(stack.url + f"/?lang={lang}")
    expect(page.locator("#wizard-overlay")).to_be_visible(timeout=3000)


def test_the_next_step_starts_from_the_top(stack_empty: Stack, admin_tablet: Page) -> None:
    try:
        page = admin_tablet
        page.set_viewport_size({"width": 800, "height": 500})
        _guide(page, stack_empty, "it")
        page.locator("#wizard-skip").click()  # step 2: persons, a long step
        expect(page.locator("#wizard-progress")).to_have_text(re.compile(r"^\D*2\D"))
        add = page.locator("#wizard-body button", has_text="Aggiungi").first
        for _ in range(4):
            add.click()
        body = page.locator("#wizard-overlay .dialog-body")
        body.evaluate("b => { b.scrollTop = b.scrollHeight; }")
        assert body.evaluate("b => b.scrollTop") > 0, "step 2 should be long enough to scroll"
        page.locator("#wizard-next").click()
        expect(page.locator("#wizard-progress")).to_have_text(re.compile(r"^\D*3\D"))
        assert body.evaluate("b => b.scrollTop") == 0
        # The buttons are still in view.
        box = page.locator("#wizard-next").bounding_box()
        assert box is not None and box["y"] + box["height"] <= 500
    finally:
        stack_empty.fake.config["configured"] = False


def test_step_5_speaks_of_the_region_in_italian(stack_empty: Stack, admin_tablet: Page) -> None:
    try:
        _guide(admin_tablet, stack_empty, "it")
        for _ in range(4):
            admin_tablet.locator("#wizard-skip").click()
        text = admin_tablet.locator("#wizard-text")
        expect(text).to_contain_text("festività della regione")
        expect(text).not_to_contain_text("Land")
        steps = admin_tablet.evaluate("FH_I18N.setLang('de') && FH_I18N.steps[4][1]")
        assert "Land" in steps or "Bundesland" in steps or "Feiertage" in steps
    finally:
        stack_empty.fake.config["configured"] = False
