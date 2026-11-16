"""0.10.0b2, "Condivisione": Nonni with reminders and notifications; templates choose the family's
calendars; a missing part of the form is outlined; a used invite shows its phone's permissions
of today; "Elimina" on a phone that is off asks first; lists on without a list say so."""

from __future__ import annotations

from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack, tablet_as
from tests.fake_ha import WASTE
from tests.helpers import ADULT_USER

PHONE_ID = "f" * 32
INVITE_ID = "a" * 32


def _device(**changes: object) -> dict[str, object]:
    device: dict[str, object] = {
        "id": PHONE_ID,
        "name": "Nonna Prova",
        "label": "Android · Chrome",
        "activated_at": "2026-11-14T10:00:00+00:00",
        "last_seen": "2026-11-15T08:00:00+00:00",
        "status": "active",
        "persons": ["sofia"],
        "categories": ["scuola"],
        "permission": "add",
        "approval": "approve",
        "notify": True,
        "push": False,
        "template": "grandparents",
        "mode": "simple",
        "features": {
            "calendar": True,
            "reminders": True,
            "lists": False,
            "waste": False,
            "weather": False,
        },
        "lists": [],
        "lists_edit": False,
    }
    device.update(changes)
    return device


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


def test_templates_turn_on_and_choose_calendars(stack_full: Stack, browser: Browser) -> None:
    _reset(stack_full)
    with tablet_as(browser, ADULT_USER) as page:
        _open_share(page, stack_full)
        form = page.locator("#share-new")
        cats = form.locator("[data-field='categories']")
        expect(cats.locator("input:checked")).to_have_count(0)
        form.locator("[data-template='grandparents']").click()
        # Nonni: reminders of the appointments and notifications on.
        expect(form.locator("[data-feature='reminders'] input")).to_be_checked()
        notify = form.locator("label", has_text="Notifiche (nuovi impegni").locator("input")
        expect(notify).to_be_checked()
        # The family's calendars of the first install are chosen.
        expect(cats.locator("label", has_text="Famiglia").locator("input")).to_be_checked()
        expect(cats.locator("label", has_text="Scuola").locator("input")).to_be_checked()
        # Another template keeps what the adult chose.
        cats.locator("label", has_text="Scuola").click()
        form.locator("[data-template='relative']").click()
        expect(cats.locator("label", has_text="Scuola").locator("input")).not_to_be_checked()
        expect(cats.locator("label", has_text="Famiglia").locator("input")).to_be_checked()
        page.fill('[data-field="name"]', "Nonna Èlia 👵")
        form.locator('[data-field="persons"] label', has_text="Sofia").click()
        form.locator("[data-template='grandparents']").click()
        form.get_by_role("button", name="Crea invito").click()
        expect(page.locator("#share-link-text")).to_be_visible()
        (create,) = _calls(stack_full, "invite_create")
        invite = create["invite"]
        assert invite["notify"] is True and invite["features"]["reminders"] is True
        assert invite["categories"] == ["famiglia"]


def test_missing_calendar_is_outlined(stack_full: Stack, browser: Browser) -> None:
    _reset(stack_full)
    with tablet_as(browser, ADULT_USER) as page:
        _open_share(page, stack_full)
        form = page.locator("#share-new")
        page.fill('[data-field="name"]', "Vicina")
        form.locator('[data-field="persons"] label', has_text="Sofia").click()
        form.get_by_role("button", name="Crea invito").click()
        cats = form.locator("[data-field='categories']")
        expect(cats).to_have_class("share-checks share-missing")
        expect(form.locator("[data-field='persons']")).not_to_have_class(
            "share-checks share-missing"
        )
        expect(page.locator("#share-error")).to_be_visible()
        assert _calls(stack_full, "invite_create") == []
        cats.locator("label", has_text="Famiglia").click()
        expect(cats).not_to_have_class("share-checks share-missing")


def test_used_invite_shows_the_phone_of_today(stack_full: Stack, browser: Browser) -> None:
    _reset(stack_full)
    stack_full.fake.guest["devices"] = [_device(persons=["sofia"], categories=["scuola"])]
    stack_full.fake.guest["invites"] = [
        {
            "id": INVITE_ID,
            "name": "Nonna Prova",
            "persons": ["luca"],
            "categories": ["famiglia"],
            "permission": "view",
            "approval": "approve",
            "notify": False,
            "created_at": "2026-11-13T10:00:00+00:00",
            "expires_at": "2026-11-20T10:00:00+00:00",
            "device_id": PHONE_ID,
            "replaces": None,
            "status": "used",
            "in_use": True,
            "template": "babysitter",
            "mode": "simple",
            "features": {"calendar": True},
            "lists": [],
            "lists_edit": False,
        }
    ]
    with tablet_as(browser, ADULT_USER) as page:
        _open_share(page, stack_full)
        card = page.locator(f"[data-invite='{INVITE_ID}']")
        current = card.locator(".share-current")
        expect(current).to_contain_text("Permessi attuali del telefono «Nonna Prova»")
        expect(current).to_contain_text("Sofia")
        expect(current).to_contain_text("Scuola")
        expect(current).to_contain_text("Nonni")
        expect(card).not_to_contain_text("Luca")


def test_delete_a_phone_that_is_off_asks_first(stack_full: Stack, browser: Browser) -> None:
    _reset(stack_full)
    stack_full.fake.guest["devices"] = [_device(status="disabled")]
    with tablet_as(browser, ADULT_USER) as page:
        _open_share(page, stack_full)
        page.click("#share-tab-devices")
        card = page.locator(f"[data-device='{PHONE_ID}']")
        card.get_by_role("button", name="Elimina").click()
        expect(page.locator("#confirm-overlay")).to_be_visible()
        expect(page.locator("#confirm-text")).to_contain_text(
            "Eliminare il telefono di «Nonna Prova»"
        )
        page.click("#confirm-cancel")
        expect(page.locator("#confirm-overlay")).to_be_hidden()
        assert _calls(stack_full, "device_remove") == []
        card.get_by_role("button", name="Elimina").click()
        page.click("#confirm-yes")
        expect(card).to_have_count(0)
        assert len(_calls(stack_full, "device_remove")) == 1


def test_lists_on_without_a_list_say_so(stack_full: Stack, browser: Browser) -> None:
    _reset(stack_full)
    with tablet_as(browser, ADULT_USER) as page:
        _open_share(page, stack_full)
        form = page.locator("#share-new")
        form.locator("[data-feature='lists']").click()
        lists = form.locator("[data-field='lists']")
        expect(lists).to_contain_text("senza liste il tasto «Liste» non compare")


def test_external_calendars_one_by_one(stack_full: Stack, browser: Browser) -> None:
    """The external calendars are in "Calendari visibili", each with its switch, off by default;
    Nonni and Babysitter propose the school's one (by its type, never its name)."""
    _reset(stack_full)
    styles = stack_full.fake.config["sources"].setdefault("calendar_styles", {})
    styles[WASTE] = {"name": "Istituto Èsempio 🏫", "type": "vacanze_scuola", "persons": []}
    try:
        with tablet_as(browser, ADULT_USER) as page:
            _open_share(page, stack_full)
            form = page.locator("#share-new")
            switch = form.locator(f"[data-external='{WASTE}'] input")
            expect(form.locator("[data-field='externals']")).to_contain_text("Istituto Èsempio 🏫")
            expect(switch).not_to_be_checked()
            form.locator("[data-template='relative']").click()
            expect(form.locator(f"[data-external='{WASTE}'] input")).not_to_be_checked()
            form.locator("[data-template='babysitter']").click()
            expect(form.locator(f"[data-external='{WASTE}'] input")).to_be_checked()
            page.fill('[data-field="name"]', "Tata Prova")
            form.locator('[data-field="persons"] label', has_text="Sofia").click()
            form.get_by_role("button", name="Crea invito").click()
            expect(page.locator("#share-link-text")).to_be_visible()
            (create,) = _calls(stack_full, "invite_create")
            assert create["invite"]["externals"] == [WASTE]
    finally:
        styles.pop(WASTE, None)


def test_external_calendars_in_permissions(stack_full: Stack, browser: Browser) -> None:
    _reset(stack_full)
    stack_full.fake.guest["devices"] = [_device(externals=[])]
    with tablet_as(browser, ADULT_USER) as page:
        _open_share(page, stack_full)
        page.click("#share-tab-devices")
        card = page.locator(f"[data-device='{PHONE_ID}']")
        card.get_by_role("button", name="Modifica permessi").click()
        card.locator(f"[data-external='{WASTE}']").click()
        card.get_by_role("button", name="Salva").click()
        expect(card.locator(".share-edit")).to_have_count(0)
        (update,) = _calls(stack_full, "device_update")
        assert update["changes"]["externals"] == [WASTE]
