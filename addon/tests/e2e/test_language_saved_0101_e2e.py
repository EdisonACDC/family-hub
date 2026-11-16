"""0.10.1: the language chosen in the guide is saved as soon as it changes (not at the last
step), so the panel, the family and the guests' web app speak the same one. Only the language is
written; the rest of the guide's draft waits for "Salva". Before the first save of a new family
it stays a preview (see test_language_0774_e2e)."""

from __future__ import annotations

import copy

from playwright.sync_api import Browser, expect

from tests.e2e.conftest import Stack, tablet_as
from tests.helpers import ADULT_USER


def test_language_is_saved_at_once(stack_full: Stack, browser: Browser) -> None:
    fake = stack_full.fake
    original = copy.deepcopy(fake.config)
    before = len(fake.saved_configs)
    try:
        with tablet_as(browser, ADULT_USER) as page:
            page.goto(stack_full.url + "/?lang=it")
            expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
            page.click("#menu-btn")
            page.click("#menu-wizard")
            expect(page.locator("#wizard-overlay")).to_be_visible()
            # Something else is changed too: it must not be saved with the language.
            page.get_by_label("Nome della famiglia").fill("Bozza non salvata")
            page.get_by_label("Lingua").select_option("de")
            expect(page.locator("#wizard-next")).to_have_text("Weiter")
            for _ in range(100):
                if len(fake.saved_configs) > before:
                    break
                page.wait_for_timeout(50)
            assert len(fake.saved_configs) == before + 1
            saved = fake.saved_configs[-1]
            assert saved["family"]["language"] == "de"
            assert saved["family"]["family_name"] == original["family"]["family_name"]
            assert saved["persons"] == original["persons"]
            assert saved["sources"]["todo"] == original["sources"]["todo"]
            # Leaving without saving keeps the language (it is saved), not the draft.
            page.keyboard.press("Escape")
            page.locator("#wizard-leave-exit").click()
            expect(page.locator("#wizard-overlay")).to_be_hidden()
            assert page.evaluate("document.documentElement.lang") == "de"
            assert len(fake.saved_configs) == before + 1
            assert fake.config["family"]["family_name"] == original["family"]["family_name"]
            # A reload still speaks German: it comes from Home Assistant.
            page.goto(stack_full.url + "/?lang=it")
            expect(page.locator("#view-switch [data-view='week'] .label-short")).to_have_text(
                "Woche", timeout=5000
            )
    finally:
        fake.config = original
        del fake.saved_configs[before:]
