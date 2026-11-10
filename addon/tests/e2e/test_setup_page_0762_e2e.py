"""0.7.6-beta.2: the page says one thing about the setup, with its button, and the guide's family
name field is as wide as the others."""

from __future__ import annotations

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_layout_071_e2e import _open
from tests.e2e.test_tablet import _device


def test_before_the_integration_is_added_only_the_setup_message_shows(
    stack_full: Stack, browser: Browser
) -> None:
    stack_full.fake.integration_installed = False
    try:
        with _device(browser, 390, 844) as page:
            _open(page, stack_full)
            expect(page.locator("#version-note")).to_be_visible(timeout=3000)
            expect(page.locator("#version-note")).to_contain_text("Family Hub:")
            # The button opens the add-integration page of Home Assistant, in the top window.
            link = page.locator("#setup-link")
            expect(link).to_be_visible()
            href = link.get_attribute("href")
            assert href == "/config/integrations/dashboard/add?domain=family_hub", href
            assert link.get_attribute("target") == "_top"
            # No second message about calendars or the add-on not reaching Home Assistant.
            expect(page.locator("#empty-note")).to_be_hidden()
            expect(page.locator("#wizard-start")).to_be_hidden()
    finally:
        stack_full.fake.integration_installed = True


def test_configured_but_no_calendar_offers_the_guide_button(
    stack_empty: Stack, admin_tablet: Page
) -> None:
    stack_empty.fake.config["configured"] = True  # set up, but no calendar yet
    try:
        tablet = admin_tablet
        tablet.set_viewport_size({"width": 390, "height": 844})
        tablet.goto(stack_empty.url + "/?lang=it")
        expect(tablet.locator("#empty-note")).to_contain_text("Nessun calendario", timeout=3000)
        expect(tablet.locator("#empty-note")).to_contain_text("menu")
        # The guide is in the menu for an adult (on a phone the top-bar button is not shown).
        expect(tablet.locator("#menu-wizard")).not_to_have_attribute("hidden", "")
        expect(tablet.locator("#setup-link")).to_be_hidden()
        expect(tablet.locator("#version-note")).to_be_hidden()
    finally:
        stack_empty.fake.config["configured"] = False


@pytest.mark.parametrize("width", [320, 390])
def test_the_family_name_field_takes_the_full_width(
    stack_empty: Stack, admin_tablet: Page, width: int
) -> None:
    stack_empty.fake.config["configured"] = False  # the guide opens by itself for a new install
    tablet = admin_tablet
    tablet.set_viewport_size({"width": width, "height": 800})
    tablet.goto(stack_empty.url + "/?lang=it")
    expect(tablet.locator("#wizard-overlay")).to_be_visible(timeout=3000)
    field = tablet.get_by_label("Nome della famiglia").bounding_box()
    body = tablet.locator("#wizard-body").bounding_box()
    assert field is not None and body is not None
    assert field["width"] >= 0.9 * body["width"], (field, body)
