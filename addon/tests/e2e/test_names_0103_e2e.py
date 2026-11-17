"""0.10.3: calendars and lists show their name (friendly_name), never an entity id like
"calendar.weekend_festivi_bw": when Home Assistant has no name for one, the id is made readable."""

from __future__ import annotations

from playwright.sync_api import Page, expect

from tests.e2e.conftest import Stack


def test_sources_show_names_not_entity_ids(stack_full: Stack, tablet: Page) -> None:
    stack_full.fake.states.append(
        {"entity_id": "calendar.weekend_festivi_bw", "state": "off", "attributes": {}}
    )
    stack_full.fake.states.append(
        {"entity_id": "todo.lavori_di_casa", "state": "0", "attributes": {}}
    )
    try:
        tablet.goto(stack_full.url + "/?lang=it")
        expect(tablet.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
        tablet.click("#menu-btn")
        tablet.click("#menu-wizard")
        expect(tablet.locator("#wizard-overlay")).to_be_visible()
        for _ in range(4):
            tablet.click("#wizard-skip")  # to "Fonti"
        body = tablet.locator("#wizard-body")
        expect(body.locator("label.check", has_text="Weekend festivi bw")).to_be_visible(
            timeout=5000
        )
        expect(body.locator("label.check", has_text="Lavori di casa")).to_be_visible()
        text = body.inner_text()
        assert "calendar.weekend" not in text and "todo.lavori" not in text
    finally:
        stack_full.fake.states[:] = [
            s
            for s in stack_full.fake.states
            if s["entity_id"] not in ("calendar.weekend_festivi_bw", "todo.lavori_di_casa")
        ]
