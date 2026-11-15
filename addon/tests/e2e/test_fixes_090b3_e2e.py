"""0.9.0b3: "Prossimi 12 mesi" as written, "Ritiri a mano" in the external calendars list right
after saving them, and refused invite attempts in the activity log."""

from __future__ import annotations

from playwright.sync_api import Browser, expect

from tests.e2e.conftest import Stack, tablet_as
from tests.e2e.test_layout_071_e2e import _open, _view
from tests.e2e.test_manual_list_0801_e2e import _pickup_day
from tests.e2e.test_tablet import _device
from tests.helpers import ADULT_USER


def test_the_list_title_is_written_as_it_is(stack_full: Stack, browser: Browser) -> None:
    with _device(browser, 1024, 768) as page:
        _open(page, stack_full)
        _view(page, "list")
        # innerText follows the CSS: no capital M in the middle of the title.
        expect(page.locator("#period-title")).to_have_text("Prossimi 12 mesi")
        _view(page, "month")
        title = page.locator("#period-title").inner_text()
        assert title[:1].isupper()  # the month keeps its capital letter


def test_saved_pickups_by_hand_show_in_the_external_list(
    stack_full: Stack, browser: Browser
) -> None:
    stack_full.fake.manual = {"rules": [], "extra": [], "skip": [], "moves": []}
    try:
        with _device(browser, 1024, 768) as page:
            _open(page, stack_full)
            page.locator("#menu-btn").click()
            page.locator("#menu-ics").click()
            ics = page.locator("#ics-overlay")
            expect(ics).to_be_visible(timeout=3000)
            expect(page.locator("#ics-body")).to_contain_text("Nessun calendario esterno")
            page.locator("#ics-manual-open").click()
            card = page.locator("#manual-body fieldset", has_text="Organico")
            card.get_by_label("C'è un ritiro").check()
            card.locator("select").first.select_option("biweekly")
            card.locator("input[type='date']").first.fill(_pickup_day())
            page.locator("#manual-save").click()
            expect(page.locator("#manual-overlay")).to_be_hidden(timeout=3000)
            # The list underneath now has the pickups, with "Modifica"; no "no calendar" note.
            item = page.locator("#ics-body .ics-card", has_text="Ritiri a mano")
            expect(item).to_be_visible(timeout=4000)
            expect(item.get_by_role("button", name="Modifica")).to_be_visible()
            expect(page.locator("#ics-body")).not_to_contain_text("Nessun calendario esterno")
    finally:
        stack_full.fake.manual = {"rules": [], "extra": [], "skip": [], "moves": []}
        stack_full.fake.events.pop("calendar.family_hub_ext_manualwaste", None)
        stack_full.fake.states = [
            s
            for s in stack_full.fake.states
            if s["entity_id"] != "calendar.family_hub_ext_manualwaste"
        ]


def test_refused_attempts_are_in_the_activity_log(stack_full: Stack, browser: Browser) -> None:
    fake = stack_full.fake
    fake.guest.update(
        {
            "invites": [],
            "devices": [],
            "pending": [],
            "log": [
                {
                    "at": "2026-11-15T09:30:00+00:00",
                    "kind": "attempt_used",
                    "name": "Nonna Èlia 👵",
                    "detail": "iPhone · Safari",
                },
                {
                    "at": "2026-11-15T09:20:00+00:00",
                    "kind": "attempt_expired",
                    "name": "Nonno",
                    "detail": "Android · Chrome",
                },
            ],
        }
    )
    with tablet_as(browser, ADULT_USER) as page:
        page.goto(stack_full.url + "/?lang=it")
        expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
        page.click("#menu-btn")
        page.click("#menu-share")
        page.click("#share-tab-devices")
        page.locator(".share-log summary").click()
        log = page.locator(".share-log")
        expect(log).to_contain_text(
            "Tentativo con invito già usato · Nonna Èlia 👵 · iPhone · Safari"
        )
        expect(log).to_contain_text("Tentativo con invito scaduto · Nonno")
    fake.guest["log"] = []
