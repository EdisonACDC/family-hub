"""0.10.2, "Condivisione": "I suoi turni sono di": a new person (guest) or one of the persons the
guest sees, in the new invite and in "Modifica permessi"."""

from __future__ import annotations

from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack, tablet_as
from tests.helpers import ADULT_USER

PHONE_ID = "d" * 32


def _open_share(page: Page, stack: Stack) -> None:
    page.goto(stack.url + "/?lang=it")
    expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
    page.click("#menu-btn")
    page.click("#menu-share")
    expect(page.locator("#share-overlay")).to_be_visible()


def _reset(stack: Stack) -> None:
    stack.fake.guest.update({"invites": [], "devices": [], "pending": [], "log": []})
    stack.fake.guest_calls.clear()


def _calls(stack: Stack, kind: str) -> list[dict[str, object]]:
    return [c for c in stack.fake.guest_calls if c["type"].endswith(kind)]


def test_new_invite_with_the_shifts_of_a_person(stack_full: Stack, browser: Browser) -> None:
    _reset(stack_full)
    with tablet_as(browser, ADULT_USER) as page:
        _open_share(page, stack_full)
        form = page.locator("#share-new")
        form.locator("[data-template='grandparents']").click()
        whose = form.locator("[data-field='shifts_person']")
        # Only the persons the guest sees are offered, after "a new person".
        options = whose.locator("option")
        assert options.all_inner_texts() == ["Una persona nuova (ospite)"]
        form.locator('[data-field="persons"] label', has_text="Mamma").click()
        assert options.all_inner_texts() == ["Una persona nuova (ospite)", "Mamma"]
        whose.select_option(label="Mamma")
        # Taking Mamma off the visible persons takes her off the choice too.
        form.locator('[data-field="persons"] label', has_text="Mamma").click()
        expect(whose).to_have_value("")
        form.locator('[data-field="persons"] label', has_text="Mamma").click()
        whose.select_option(label="Mamma")
        page.fill('[data-field="name"]', "Tata Prova")
        form.get_by_role("button", name="Crea invito").click()
        expect(page.locator("#share-link-text")).to_be_visible()
        (create,) = _calls(stack_full, "invite_create")
        invite = create["invite"]
        assert invite["has_shifts"] is True and invite["shifts_person"] == "mamma"
        assert "mamma" in invite["persons"]


def test_a_phone_moves_to_a_person_in_permissions(stack_full: Stack, browser: Browser) -> None:
    _reset(stack_full)
    stack_full.fake.guest["devices"] = [
        {
            "id": PHONE_ID,
            "name": "Veronica",
            "label": "Android · Chrome",
            "activated_at": "2026-11-14T10:00:00+00:00",
            "last_seen": "2026-11-15T08:00:00+00:00",
            "status": "active",
            "persons": ["sofia", "mamma"],
            "categories": ["scuola"],
            "permission": "add",
            "approval": "approve",
            "notify": True,
            "push": False,
            "has_shifts": True,
            "shifts_person": "",
            "person_id": "guest_abc12345",
            "template": "grandparents",
            "mode": "simple",
            "features": {"calendar": True},
            "lists": [],
            "lists_edit": False,
        }
    ]
    with tablet_as(browser, ADULT_USER) as page:
        _open_share(page, stack_full)
        page.click("#share-tab-devices")
        card = page.locator(f"[data-device='{PHONE_ID}']")
        card.get_by_role("button", name="Modifica permessi").click()
        card.locator("[data-field='shifts_person']").select_option(label="Mamma")
        card.get_by_role("button", name="Salva").click()
        expect(card.locator(".share-edit")).to_have_count(0)
        (update,) = _calls(stack_full, "device_update")
        assert update["changes"]["shifts_person"] == "mamma"
