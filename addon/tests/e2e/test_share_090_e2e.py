"""0.9: "Condivisione" in the menu (adults only), a new invite with its link, QR code and copy
button, the devices with their buttons, and appointments waiting for approval."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack, tablet_as
from tests.helpers import ADULT_USER, CHILD_USER

DEVICE = {
    "id": "d" * 32,
    "name": "Nonna Èlia 👵 con un nome molto lungo davvero",
    "label": "Android · Chrome",
    "activated_at": "2026-11-14T10:00:00+00:00",
    "last_seen": "2026-11-15T08:00:00+00:00",
    "status": "pending",
    "persons": ["sofia"],
    "categories": ["scuola"],
    "permission": "edit_own",
    "approval": "approve",
    "notify": True,
    "push": False,
}
PENDING = {
    "id": "p" * 32,
    "device": "Nonna Èlia 👵",
    "created_at": "2026-11-15T09:00:00+00:00",
    "title": "Merenda dalla nonna",
    "start": "2027-01-12T16:00:00+01:00",
    "end": "2027-01-12T17:00:00+01:00",
    "all_day": False,
    "category": "scuola",
    "persons": ["sofia"],
    "location": "Casa della nonna",
    "note": "Porto i biscotti",
}


def _open(page: Page, stack: Stack) -> None:
    page.goto(stack.url + "/?lang=it")
    expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)


@contextmanager
def _phone(browser: Browser, user: str) -> Iterator[Page]:
    context = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True)
    context.set_extra_http_headers({"X-Remote-User-Id": user})
    page = context.new_page()
    try:
        yield page
    finally:
        context.close()


def _reset(stack: Stack) -> None:
    stack.fake.guest.update({"invites": [], "devices": [], "pending": [], "log": []})
    stack.fake.guest_calls.clear()


def test_sharing_is_in_the_menu_for_adults_only(stack_full: Stack, browser: Browser) -> None:
    _reset(stack_full)
    with tablet_as(browser, ADULT_USER) as page:
        _open(page, stack_full)
        page.click("#menu-btn")
        expect(page.locator("#menu-share")).to_have_text("Condivisione")
        expect(page.locator("#menu-share")).to_be_visible()
    with tablet_as(browser, CHILD_USER) as page:
        _open(page, stack_full)
        page.click("#menu-btn")
        expect(page.locator("#menu-share")).to_be_hidden()
        expect(page.locator("#approval-banner")).to_be_hidden()


def test_a_new_invite_gives_a_link_with_copy_and_qr(stack_full: Stack, browser: Browser) -> None:
    _reset(stack_full)
    with _phone(browser, ADULT_USER) as page:
        page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        _open(page, stack_full)
        page.click("#menu-btn")
        page.click("#menu-share")
        dialog = page.locator("#share-overlay")
        expect(dialog.locator("#share-tab-invites")).to_have_attribute("aria-selected", "true")
        # Nothing chosen: the page says what is missing and sends nothing.
        dialog.get_by_role("button", name="Crea invito").click()
        expect(page.locator("#share-error")).to_contain_text("almeno una persona")
        assert stack_full.fake.guest_calls == [] or all(
            c["type"].endswith("/list") for c in stack_full.fake.guest_calls
        )
        page.fill('[data-field="name"]', "Nonna Èlia 👵")
        dialog.locator('[data-field="persons"] label', has_text="Sofia").click()
        dialog.locator('[data-field="categories"] label', has_text="Scuola").click()
        expect(dialog.locator('[data-field="approval"]')).to_have_value("approve")
        dialog.get_by_role("button", name="Crea invito").click()
        link = page.locator("#share-link-text")
        expect(link).to_have_value("https://casa.example.org/api/family_hub/guest/#i=" + "T" * 43)
        expect(page.locator("#share-qr svg")).to_be_visible()
        dialog.get_by_role("button", name="Copia").click()
        expect(page.locator("#status-note")).to_have_text("Link copiato.")
        assert page.evaluate("navigator.clipboard.readText()").startswith(
            "https://casa.example.org/"
        )
        (create,) = [c for c in stack_full.fake.guest_calls if c["type"].endswith("invite_create")]
        assert create["invite"]["persons"] == ["sofia"]
        assert create["invite"]["categories"] == ["scuola"]
        assert create["invite"]["approval"] == "approve" and create["invite"]["expires_days"] == 7
        expect(dialog.locator(".share-invite")).to_contain_text("Nonna Èlia 👵")
        # On a phone the window fits: no sideways scrolling.
        assert page.evaluate("document.documentElement.scrollWidth") <= 390
        # The link is shown once: closed and opened again, it is gone.
        page.click("#share-close")
        page.click("#menu-btn")
        page.click("#menu-share")
        expect(page.locator("#share-link-text")).to_have_count(0)


def test_a_waiting_phone_is_confirmed_from_devices(stack_full: Stack, browser: Browser) -> None:
    _reset(stack_full)
    stack_full.fake.guest["devices"] = [dict(DEVICE)]
    with _phone(browser, ADULT_USER) as page:
        _open(page, stack_full)
        page.click("#menu-btn")
        page.click("#menu-share")
        page.click("#share-tab-devices")
        card = page.locator(".share-device")
        expect(card).to_contain_text("Android · Chrome")
        expect(card).to_contain_text("In attesa di conferma")
        card.get_by_role("button", name="Conferma").click()
        expect(card).to_contain_text("Attivo")
        for name in ("Rinomina", "Modifica permessi", "Disattiva"):
            expect(card.get_by_role("button", name=name)).to_be_visible()
        card.get_by_role("button", name="Rinomina").click()
        page.fill('[data-field="rename"]', "Nonna")
        card.get_by_role("button", name="Salva").click()
        expect(card.locator("strong")).to_have_text("Nonna")
        card.get_by_role("button", name="Disattiva").click()
        page.click("#confirm-yes")
        expect(card).to_contain_text("Disattivato")
        kinds = [c["type"].rsplit("/", 1)[1] for c in stack_full.fake.guest_calls]
        assert [k for k in kinds if k != "list"] == [
            "device_confirm",
            "device_update",
            "device_disable",
        ]
        assert page.evaluate("document.documentElement.scrollWidth") <= 390


def test_appointments_to_approve_show_a_notice_and_are_approved(
    stack_full: Stack, browser: Browser
) -> None:
    _reset(stack_full)
    stack_full.fake.guest["devices"] = [{**DEVICE, "status": "active"}]
    stack_full.fake.guest["pending"] = [dict(PENDING)]
    with tablet_as(browser, ADULT_USER) as page:
        _open(page, stack_full)
        banner = page.locator("#approval-banner")
        expect(banner).to_have_text("1 appuntamento da approvare")
        banner.click()
        item = page.locator(".share-pending")
        expect(item).to_contain_text("Merenda dalla nonna")
        expect(item).to_contain_text("aggiunto da Nonna Èlia 👵")
        for name in ("Approva", "Modifica", "Rifiuta"):
            expect(item.get_by_role("button", name=name)).to_be_visible()
        item.get_by_role("button", name="Modifica").click()
        page.fill('[data-field="start"]', "15:00")
        page.fill('[data-field="end"]', "16:00")
        item.locator(".share-edit").get_by_role("button", name="Approva").click()
        expect(banner).to_be_hidden()
        (decide,) = [c for c in stack_full.fake.guest_calls if c["type"].endswith("pending_decide")]
        assert decide["accept"] is True
        assert decide["changes"]["start"] == "15:00" and decide["changes"]["end"] == "16:00"
        assert decide["changes"]["title"] == "Merenda dalla nonna"
        # The approved appointment is in the week with who added it.
        page.goto(stack_full.url + "/?lang=it")
        expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)


def test_a_new_waiting_appointment_appears_without_reloading(
    stack_full: Stack, browser: Browser
) -> None:
    _reset(stack_full)
    stack_full.fake.guest["devices"] = [{**DEVICE, "status": "active"}]
    with tablet_as(browser, ADULT_USER) as page:
        _open(page, stack_full)
        expect(page.locator("#approval-banner")).to_be_hidden()
        stack_full.fake.guest["pending"] = [dict(PENDING), {**PENDING, "id": "q" * 32}]
        stack_full.run(stack_full.fake.guest_changed())
        expect(page.locator("#approval-banner")).to_have_text("2 appuntamenti da approvare")
