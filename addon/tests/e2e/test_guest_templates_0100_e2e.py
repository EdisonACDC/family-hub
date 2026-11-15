"""0.10: in "Condivisione" the adult chooses, per guest, a template (Nonni, Babysitter,
Familiare, Personalizzato), the mode (Semplice / Completa) and each function. By default only the
calendar, read only. Everything stays editable, also later in "Modifica permessi"."""

from __future__ import annotations

from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack, tablet_as
from tests.helpers import ADULT_USER

DEVICE = {
    "id": "e" * 32,
    "name": "Nonna Prova",
    "label": "Android · Chrome",
    "activated_at": "2026-11-14T10:00:00+00:00",
    "last_seen": "2026-11-15T08:00:00+00:00",
    "status": "active",
    "persons": ["sofia"],
    "categories": ["scuola"],
    "permission": "add",
    "approval": "approve",
    "notify": False,
    "push": False,
    "template": "grandparents",
    "mode": "simple",
    "features": {
        "calendar": True,
        "reminders": False,
        "lists": False,
        "waste": False,
        "weather": False,
    },
    "lists": [],
    "lists_edit": False,
}


def _open_share(page: Page, stack: Stack) -> None:
    page.goto(stack.url + "/?lang=it")
    expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
    page.click("#menu-btn")
    page.click("#menu-share")
    expect(page.locator("#share-overlay")).to_be_visible()


def _reset(stack: Stack) -> None:
    stack.fake.guest.update({"invites": [], "devices": [], "pending": [], "log": []})
    stack.fake.guest_calls.clear()


def _switch(page: Page, feature: str) -> object:
    return page.locator(f"#share-new [data-feature='{feature}'] input")


def test_templates_and_functions_of_a_new_invite(stack_full: Stack, browser: Browser) -> None:
    _reset(stack_full)
    with tablet_as(browser, ADULT_USER) as page:
        errors: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        _open_share(page, stack_full)
        form = page.locator("#share-new")
        # Default: Personalizzato, Semplice, only the calendar, read only, no notifications.
        expect(form.locator("[data-template='custom']")).to_have_attribute("aria-pressed", "true")
        expect(form.locator("[data-field='mode']")).to_have_value("simple")
        expect(form.locator("[data-field='permission']")).to_have_value("view")
        expect(_switch(page, "calendar")).to_be_checked()
        for name in ("reminders", "lists", "waste", "weather"):
            expect(_switch(page, name)).not_to_be_checked()
        expect(form).to_contain_text("Mai agli invitati")
        # Nonni: Semplice, add appointments, own shifts.
        form.locator("[data-template='grandparents']").click()
        expect(form.locator("[data-template='grandparents']")).to_have_attribute(
            "aria-pressed", "true"
        )
        expect(form.locator("[data-field='permission']")).to_have_value("add")
        expect(form.locator("[data-field='shifts-box']")).to_be_visible()
        # Babysitter: read only, nothing else.
        form.locator("[data-template='babysitter']").click()
        expect(form.locator("[data-field='permission']")).to_have_value("view")
        expect(form.locator("[data-field='shifts-box']")).to_be_hidden()
        # Familiare: Completa, then the lists chosen by hand.
        form.locator("[data-template='relative']").click()
        expect(form.locator("[data-field='mode']")).to_have_value("full")
        expect(form.locator("[data-field='permission']")).to_have_value("edit_own")
        expect(_switch(page, "weather")).to_be_checked()
        expect(form.locator("[data-field='lists']")).to_be_hidden()
        form.locator("[data-feature='lists']").click()
        lists = form.locator("[data-field='lists']")
        expect(lists).to_be_visible()
        lists.locator("label", has_text="Spesa").click()
        page.fill('[data-field="name"]', "Zia Èlia 👩")
        form.locator('[data-field="persons"] label', has_text="Sofia").click()
        form.locator('[data-field="categories"] label', has_text="Scuola").click()
        form.get_by_role("button", name="Crea invito").click()
        expect(page.locator("#share-link-text")).to_be_visible()
        (create,) = [c for c in stack_full.fake.guest_calls if c["type"].endswith("invite_create")]
        invite = create["invite"]
        assert invite["template"] == "relative" and invite["mode"] == "full"
        assert invite["permission"] == "edit_own" and invite["approval"] == "direct"
        assert invite["features"] == {
            "calendar": True,
            "reminders": True,
            "lists": True,
            "waste": True,
            "weather": True,
        }
        assert invite["lists"] == ["todo.spesa"] and invite["lists_edit"] is False
        assert errors == []


def test_functions_change_later_in_permissions(stack_full: Stack, browser: Browser) -> None:
    _reset(stack_full)
    stack_full.fake.guest["devices"] = [dict(DEVICE)]
    with tablet_as(browser, ADULT_USER) as page:
        _open_share(page, stack_full)
        page.click("#share-tab-devices")
        card = page.locator(f"[data-device='{'e' * 32}']")
        expect(card).to_contain_text("Nonni (Semplice)")
        card.get_by_role("button", name="Modifica permessi").click()
        card.locator("[data-feature='weather']").click()
        card.locator("[data-field='mode']").select_option("full")
        card.get_by_role("button", name="Salva").click()
        expect(card.locator(".share-edit")).to_have_count(0)
        (update,) = [c for c in stack_full.fake.guest_calls if c["type"].endswith("device_update")]
        changes = update["changes"]
        assert changes["features"]["weather"] is True and changes["features"]["calendar"] is True
        assert changes["mode"] == "full" and changes["template"] == "grandparents"
        assert changes["permission"] == "add"
