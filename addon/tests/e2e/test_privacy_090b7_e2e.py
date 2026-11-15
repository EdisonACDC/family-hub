"""0.9.0b7: "Privato" in the event form, the warning for an appointment with no person (only when
the family has guests), and the new switches of an invite and a phone."""

from __future__ import annotations

from typing import Any

from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack, tablet_as
from tests.e2e.test_share_090_e2e import DEVICE
from tests.fake_ha import FAMILY, stored_event
from tests.helpers import ADULT_USER


def _reset(stack: Stack, devices: list[dict[str, Any]] | None = None) -> None:
    stack.fake.guest.update({"invites": [], "devices": devices or [], "pending": [], "log": []})
    stack.fake.guest_calls.clear()
    stack.fake.calls.clear()


def _open(page: Page, stack: Stack) -> None:
    page.goto(stack.url + "/?lang=it")
    expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)


def _new_event(page: Page, summary: str) -> None:
    page.locator("#add-btn").click()
    expect(page.locator("#event-form")).to_be_visible()
    page.fill("#event-form input[name='summary']", summary)


def _saved(stack: Stack, summary: str) -> list[dict[str, Any]]:
    return [
        c["data"]
        for c in stack.fake.calls
        if c["service"] == "add_event" and c["data"].get("summary") == summary
    ]


def test_no_person_warning_only_with_guests(stack_full: Stack, browser: Browser) -> None:
    # Without guests: saved at once, as before.
    _reset(stack_full)
    with tablet_as(browser, ADULT_USER) as page:
        _open(page, stack_full)
        _new_event(page, "Spesa grande")
        expect(page.locator("#event-private-row")).to_be_hidden()
        page.locator("#event-form button[type='submit']").click()
        expect(page.locator("#event-form")).to_be_hidden()
        assert len(_saved(stack_full, "Spesa grande")) == 1
    # With a guest phone: the warning first.
    _reset(stack_full, [{**DEVICE, "status": "active"}])
    with tablet_as(browser, ADULT_USER) as page:
        _open(page, stack_full)
        _new_event(page, "PEDIATRA")
        page.locator("#event-form button[type='submit']").click()
        warning = page.locator("#no-person-warning")
        expect(warning).to_contain_text(
            "Nessuna persona scelta: gli ospiti non vedranno questo appuntamento."
        )
        assert _saved(stack_full, "PEDIATRA") == []
        # "Scegli persone" goes back to the form.
        page.click("#no-person-choose")
        expect(warning).to_be_hidden()
        expect(page.locator("#event-form")).to_be_visible()
        page.locator("#event-form button[type='submit']").click()
        page.click("#no-person-save")
        expect(page.locator("#event-form")).to_be_hidden()
        assert len(_saved(stack_full, "PEDIATRA")) == 1


def test_private_switch_and_card(stack_full: Stack, browser: Browser) -> None:
    _reset(stack_full, [{**DEVICE, "status": "active"}])
    event = stored_event(
        "Colloquio riservato", "2026-11-20T10:00:00+01:00", "2026-11-20T11:00:00+01:00", "mamma"
    )
    event["private"] = True
    with tablet_as(browser, ADULT_USER) as page:
        _open(page, stack_full)
        _new_event(page, "Visita privata")
        row = page.locator("#event-private-row")
        expect(row).to_be_visible()
        expect(row).to_contain_text("Privato")
        expect(page.locator("#event-private-hint")).to_contain_text("non va mai agli ospiti")
        page.locator("#event-persons label", has_text="Mamma").first.click()
        page.locator("#event-private").check()
        page.locator("#event-form button[type='submit']").click()
        expect(page.locator("#event-form")).to_be_hidden()
        (data,) = _saved(stack_full, "Visita privata")
        assert data["private"] is True
    # Not private: the field is not sent (as before).
    _reset(stack_full, [{**DEVICE, "status": "active"}])
    with tablet_as(browser, ADULT_USER) as page:
        _open(page, stack_full)
        _new_event(page, "Visita normale")
        page.locator("#event-persons label", has_text="Mamma").first.click()
        page.locator("#event-form button[type='submit']").click()
        expect(page.locator("#event-form")).to_be_hidden()
        (data,) = _saved(stack_full, "Visita normale")
        assert "private" not in data
    del event


def test_invite_and_phone_switches(stack_full: Stack, browser: Browser) -> None:
    _reset(
        stack_full,
        [
            {
                **DEVICE,
                "status": "active",
                "push_status": "active",
                "family_events": False,
                "notify_new": True,
                "reminder_offsets": None,
                "quiet_start": None,
                "quiet_end": None,
            }
        ],
    )
    with tablet_as(browser, ADULT_USER) as page:
        _open(page, stack_full)
        page.click("#menu-btn")
        page.click("#menu-share")
        new = page.locator("#share-new")
        expect(new).to_contain_text(
            "Mostra anche gli appuntamenti senza persona, solo nei calendari scelti"
        )
        expect(new).to_contain_text("Attenzione: potrebbero esserci impegni degli adulti")
        page.fill('[data-field="name"]', "Nonno")
        new.locator('[data-field="persons"] label', has_text="Sofia").click()
        new.locator('[data-field="categories"] label', has_text="Scuola").click()
        new.locator("label.switch-row", has_text="senza persona").locator("input").check()
        new.get_by_role("button", name="Crea invito").click()
        expect(page.locator("#share-link-text")).to_be_visible()
        (create,) = [c for c in stack_full.fake.guest_calls if c["type"].endswith("invite_create")]
        assert create["invite"]["family_events"] is True
        page.click("#share-tab-devices")
        card = page.locator(".share-device")
        card.get_by_role("button", name="Modifica permessi").click()
        switch = card.locator("label.switch-row", has_text="Avvisa per i nuovi impegni").locator(
            "input"
        )
        expect(switch).to_be_checked()
        switch.uncheck()
        card.locator(".share-edit").get_by_role("button", name="Salva").click()
        expect(card.locator(".share-edit")).to_have_count(0)
        updates = [c for c in stack_full.fake.guest_calls if c["type"].endswith("device_update")]
        assert updates[-1]["changes"]["notify_new"] is False
        assert updates[-1]["changes"]["family_events"] is False
    assert FAMILY
