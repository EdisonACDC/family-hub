"""0.7.8b1: the project's support link is one discreet entry at the foot of the menu, in the family's
language, opening the Ko-fi page in a new tab. Nothing else in the app asks for money."""

from __future__ import annotations

import pytest
from playwright.sync_api import Browser, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_layout_071_e2e import _open
from tests.e2e.test_tablet import _device

LINK = "https://ko-fi.com/edisonacdc"


@pytest.mark.parametrize(
    ("language", "text"),
    [
        ("it", "☕ Supporta il progetto"),
        ("de", "☕ Projekt unterstützen"),
        ("en", "☕ Support the project"),
    ],
)
def test_the_support_link_is_at_the_foot_of_the_menu(
    stack_full: Stack, browser: Browser, language: str, text: str
) -> None:
    stack_full.fake.config["family"] = {
        **stack_full.fake.config.get("family", {}),
        "language": language,
    }
    try:
        with _device(browser, 390, 844) as page:
            _open(page, stack_full)
            page.locator("#menu-btn").click()
            link = page.locator("#menu-support")
            expect(link).to_be_visible()
            expect(link).to_have_text(text)
            assert link.get_attribute("href") == LINK
            assert link.get_attribute("target") == "_blank"
            assert "noopener" in (link.get_attribute("rel") or "")
            # It is the last entry of the menu.
            assert (
                page.evaluate("document.querySelector('#menu > :last-child').id") == "menu-support"
            )
    finally:
        stack_full.fake.config["family"] = {
            **stack_full.fake.config.get("family", {}),
            "language": "it",
        }
