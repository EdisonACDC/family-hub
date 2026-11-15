"""0.9.0b6: a tapped notification opens Family Hub on what it is about (a phone waiting, an
appointment to approve, a reminder's event), and each guest phone's notification settings."""

from __future__ import annotations

from datetime import date, timedelta

from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack, tablet_as
from tests.e2e.test_share_090_e2e import DEVICE, PENDING
from tests.fake_ha import FAMILY, stored_event
from tests.helpers import ADULT_USER

OTHER = {**DEVICE, "id": "e" * 32, "name": "Nonno Pino", "label": "iPhone · Safari"}


def _reset(stack: Stack) -> None:
    stack.fake.guest.update({"invites": [], "devices": [], "pending": [], "log": []})
    stack.fake.guest_calls.clear()


def _open(page: Page, stack: Stack, query: str = "") -> None:
    page.goto(stack.url + "/?lang=it" + query)
    expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)


def test_a_phone_request_opens_devices_on_that_phone(stack_full: Stack, browser: Browser) -> None:
    _reset(stack_full)
    stack_full.fake.guest["devices"] = [dict(DEVICE), {**OTHER, "status": "pending"}]
    with tablet_as(browser, ADULT_USER) as page:
        _open(page, stack_full, f"&fh_open=device.{OTHER['id']}")
        expect(page.locator("#share-overlay")).to_be_visible()
        expect(page.locator("#share-tab-devices")).to_have_attribute("aria-selected", "true")
        expect(page.locator(f"[data-device='{OTHER['id']}']")).to_have_class(
            "share-card share-device share-pending share-highlight"
        )
        expect(page.locator(f"[data-device='{DEVICE['id']}']")).not_to_have_class(
            "share-card share-device share-pending share-highlight"
        )
        # Read once: the address no longer has it.
        assert "fh_open" not in page.url


def test_an_approval_request_opens_that_appointment(stack_full: Stack, browser: Browser) -> None:
    _reset(stack_full)
    second = {**PENDING, "id": "b" * 32, "title": "Pizza dalla nonna"}
    stack_full.fake.guest["devices"] = [{**DEVICE, "status": "active"}]
    stack_full.fake.guest["pending"] = [dict(PENDING), second]
    with tablet_as(browser, ADULT_USER) as page:
        _open(page, stack_full, f"&fh_open=pending.{second['id']}")
        expect(page.locator("#approvals-overlay")).to_be_visible()
        highlighted = page.locator(".share-pending.share-highlight")
        expect(highlighted).to_have_count(1)
        expect(highlighted).to_contain_text("Pizza dalla nonna")


def test_a_reminder_opens_its_event_on_its_day(stack_full: Stack, browser: Browser) -> None:
    _reset(stack_full)
    day = (date.today() + timedelta(days=9)).isoformat()
    event = stored_event(
        "Dentista di Sofia",
        f"{day}T15:00:00+01:00",
        f"{day}T16:00:00+01:00",
        "sofia",
        record_id="d" * 32,
    )
    stack_full.fake.events[FAMILY].append(event)
    try:
        with tablet_as(browser, ADULT_USER) as page:
            _open(page, stack_full, f"&fh_open=event.{'d' * 32}.{day}")
            card = page.locator("#card-overlay")
            expect(card).to_be_visible()
            expect(card.locator(".card-title")).to_have_text("Dentista di Sofia")
            # The week shown is the one of that day.
            page.locator("#card-overlay").get_by_role("button", name="Chiudi").click()
            expect(page.locator("#week")).to_contain_text("Dentista di Sofia")
    finally:
        stack_full.fake.events[FAMILY].remove(event)


def test_each_phone_shows_its_notifications_and_sends_a_test(
    stack_full: Stack, browser: Browser
) -> None:
    _reset(stack_full)
    active = {
        **DEVICE,
        "status": "active",
        "push_status": "blocked",
        "reminder_offsets": None,
        "quiet_start": None,
        "quiet_end": None,
    }
    stack_full.fake.guest["devices"] = [active]
    with tablet_as(browser, ADULT_USER) as page:
        _open(page, stack_full)
        page.click("#menu-btn")
        page.click("#menu-share")
        page.click("#share-tab-devices")
        card = page.locator(".share-device")
        expect(card).to_contain_text("Notifiche: Bloccate · promemoria come la famiglia")
        card.get_by_role("button", name="Invia notifica di prova").click()
        expect(page.locator("#status-note")).to_have_text("Notifica di prova inviata.")
        card.get_by_role("button", name="Modifica permessi").click()
        page.select_option("[data-field='own-mode']", "own")
        page.fill("[data-field='own-minutes']", "60, 15")
        page.fill("[data-field='quiet_start']", "21:30")
        page.fill("[data-field='quiet_end']", "07:30")
        card.locator(".share-edit").get_by_role("button", name="Salva").click()
        expect(card).to_contain_text("promemoria 60, 15 minuti prima · silenzio 21:30–07:30")
        kinds = [c for c in stack_full.fake.guest_calls if c["type"].endswith("device_update")]
        changes = kinds[-1]["changes"]
        assert changes["reminder_offsets"] == [60, 15]
        assert (changes["quiet_start"], changes["quiet_end"]) == ("21:30", "07:30")
        assert any(c["type"].endswith("device_test_push") for c in stack_full.fake.guest_calls)
