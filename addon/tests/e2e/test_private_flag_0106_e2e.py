"""0.10.6: an ordinary appointment is not private. Home Assistant sends the flag as text
("False"), which the add-on used to read as true: the card showed a lock, the form opened with
"Privato" on, and a save made the appointment private (it then vanished for the guests).
A private one stays so."""

from __future__ import annotations

import re
from datetime import date

from playwright.sync_api import Browser, expect

from tests.e2e.conftest import Stack, tablet_as
from tests.e2e.test_layout_071_e2e import _open, _view
from tests.fake_ha import FAMILY, stored_event
from tests.helpers import ADULT_USER

SUMMARY = "Visita normale"


def _seed(stack: Stack, private: bool) -> None:
    today = date.today().isoformat()
    record = stored_event(SUMMARY, f"{today} 10:00:00", f"{today} 11:00:00", "mamma")
    record["private"] = private
    stack.fake.events[FAMILY][:] = [record]
    stack.fake.guest.update({"invites": [], "devices": [], "pending": [], "log": []})
    stack.fake.calls.clear()


def _card_then_edit_and_save(page) -> None:  # type: ignore[no-untyped-def]
    page.locator(".event", has_text=SUMMARY).first.click()
    expect(page.locator("#card-overlay")).to_be_visible(timeout=3000)


def test_an_ordinary_appointment_is_not_private_in_the_card_the_form_or_after_a_save(
    stack_full: Stack, browser: Browser
) -> None:
    _seed(stack_full, private=False)
    with tablet_as(browser, ADULT_USER) as page:
        _open(page, stack_full)
        _view(page, "week")
        _card_then_edit_and_save(page)
        expect(page.locator(".card-private")).to_have_count(0)
        page.locator("#card-foot button", has_text=re.compile("Modifica|Edit|Bearbeiten")).click()
        expect(page.locator("#event-form")).to_be_visible(timeout=3000)
        expect(page.locator("#event-private")).not_to_be_checked()
        page.locator("#event-form button[type='submit']").click()
        expect(page.locator("#event-form")).to_be_hidden(timeout=3000)
    sent = [c["data"] for c in stack_full.fake.calls if c["service"] == "update_event"]
    assert sent, "the save was sent"
    assert sent[-1].get("private") is not True, sent[-1]


def test_a_private_appointment_stays_private_when_it_is_saved(
    stack_full: Stack, browser: Browser
) -> None:
    _seed(stack_full, private=True)
    with tablet_as(browser, ADULT_USER) as page:
        _open(page, stack_full)
        _view(page, "week")
        _card_then_edit_and_save(page)
        expect(page.locator(".card-private")).to_have_count(1)
        page.locator("#card-foot button", has_text=re.compile("Modifica|Edit|Bearbeiten")).click()
        expect(page.locator("#event-form")).to_be_visible(timeout=3000)
        expect(page.locator("#event-private")).to_be_checked()
        page.locator("#event-form button[type='submit']").click()
        expect(page.locator("#event-form")).to_be_hidden(timeout=3000)
    sent = [c["data"] for c in stack_full.fake.calls if c["service"] == "update_event"]
    assert sent[-1].get("private") is True, sent[-1]
