"""0.9.0b8: a guest with its own work shifts, from the adults' side: the invite's switch with its
colour and calendar, keep or delete the shifts when the phone is removed, and the notice switch."""

from __future__ import annotations

from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack, tablet_as
from tests.e2e.test_share_090_e2e import DEVICE
from tests.helpers import ADULT_USER


def _open_share(page: Page, stack: Stack) -> None:
    page.goto(stack.url + "/?lang=it")
    expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
    page.click("#menu-btn")
    page.click("#menu-share")


def _reset(stack: Stack, devices: list[dict] | None = None) -> None:
    stack.fake.guest.update({"invites": [], "devices": devices or [], "pending": [], "log": []})
    stack.fake.guest_calls.clear()


def test_an_invite_with_its_own_shifts(stack_full: Stack, browser: Browser) -> None:
    _reset(stack_full)
    with tablet_as(browser, ADULT_USER) as page:
        _open_share(page, stack_full)
        new = page.locator("#share-new")
        box = new.locator("[data-field='shifts-box']")
        expect(box).to_be_hidden()
        page.fill('[data-field="name"]', "Nonna Ines")
        new.locator('[data-field="persons"] label', has_text="Sofia").click()
        new.locator('[data-field="categories"] label', has_text="Scuola").click()
        new.locator("label.switch-row", has_text="Ha i suoi turni di lavoro").locator(
            "input"
        ).check()
        expect(box).to_be_visible()
        expect(box).to_contain_text("senza account di Home Assistant")
        box.locator("[data-field='shift_color']").fill("#0ea5e9")
        box.locator("[data-field='shifts_category']").select_option("scuola")
        new.get_by_role("button", name="Crea invito").click()
        expect(page.locator("#share-link-text")).to_be_visible()
        (create,) = [c for c in stack_full.fake.guest_calls if c["type"].endswith("invite_create")]
        invite = create["invite"]
        assert invite["has_shifts"] is True and invite["shift_color"] == "#0ea5e9"
        assert invite["shifts_category"] == "scuola"


def test_removing_a_phone_with_shifts_asks_keep_or_delete(
    stack_full: Stack, browser: Browser
) -> None:
    _reset(
        stack_full,
        [{**DEVICE, "status": "disabled", "person_id": "guest_1234abcd", "has_shifts": True}],
    )
    with tablet_as(browser, ADULT_USER) as page:
        _open_share(page, stack_full)
        page.click("#share-tab-devices")
        card = page.locator(".share-device")
        card.get_by_role("button", name="Elimina").click()
        ask = card.locator(".share-keep-shifts")
        expect(ask).to_contain_text("ha dei turni: tenerli nel calendario o cancellarli?")
        assert not [c for c in stack_full.fake.guest_calls if c["type"].endswith("device_remove")]
        ask.get_by_role("button", name="Tieni i turni").click()
        expect(page.locator(".share-device")).to_have_count(0)
        (remove,) = [c for c in stack_full.fake.guest_calls if c["type"].endswith("device_remove")]
        assert remove["keep_shifts"] is True


def test_the_shifts_notice_can_be_switched_off(stack_full: Stack, browser: Browser) -> None:
    _reset(stack_full)
    with tablet_as(browser, ADULT_USER) as page:
        _open_share(page, stack_full)
        box = page.locator("#share-recipients")
        switch = box.locator("label.switch-row", has_text="cambia i suoi turni").locator("input")
        expect(switch).to_be_checked()
        switch.uncheck()
        box.get_by_role("button", name="Salva").click()
        expect(page.locator("#status-note")).to_have_text("Salvato.")
        (call,) = [c for c in stack_full.fake.guest_calls if c["type"].endswith("recipients_save")]
        assert call["recipients"]["shifts"] is False
