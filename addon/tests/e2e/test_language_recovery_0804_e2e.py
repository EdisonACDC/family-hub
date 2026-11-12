"""0.8.0b4: when Home Assistant does not answer yet (after a restart), the page does not guess the
family's language; once it answers, the page takes the family's settings without a reload."""

from __future__ import annotations

import time

from playwright.sync_api import Browser, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_tablet import _device


def test_the_page_takes_the_family_language_once_home_assistant_answers(
    stack_full: Stack, browser: Browser
) -> None:
    stack_full.fake.config["family"] = {
        **stack_full.fake.config.get("family", {}),
        "language": "de",
    }
    stack_full.fake.config_refused_until = time.monotonic() + 4
    try:
        with _device(browser, 390, 844) as page:
            # Until Home Assistant answers, the page keeps the language it started with (?lang=it).
            page.goto(stack_full.url + "/?lang=it")
            label = page.locator("#view-switch [data-view='week'] .label-short")
            expect(label).to_have_text("Sett.", timeout=3000)
            # Home Assistant answers: the family's German, with no reload.
            expect(label).to_have_text("Woche", timeout=15000)
            assert page.evaluate("document.documentElement.lang") == "de"
    finally:
        stack_full.fake.config_refused_until = 0.0
        stack_full.fake.config["family"] = {
            **stack_full.fake.config.get("family", {}),
            "language": "it",
        }
