"""Importing an old calendar in the browser: preview, import, and a second import adds nothing."""

from __future__ import annotations

from datetime import date, timedelta

from playwright.sync_api import Page, expect

from tests.e2e.conftest import Stack
from tests.fake_ha import stored_event


def _open_sources_step(page: Page, stack: Stack) -> None:
    page.goto(stack.url + "/?lang=it")
    expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
    page.locator("#menu-btn").click()
    page.locator("#menu-wizard").click()
    expect(page.locator("#wizard-overlay")).to_be_visible(timeout=3000)
    for _ in range(4):
        page.locator("#wizard-next").click()
    expect(page.locator("#wizard-progress")).to_have_text("Passo 5 di 6")


def test_preview_then_import_then_nothing_new(stack_full: Stack, tablet: Page) -> None:
    fake = stack_full.fake
    today = date.today()
    fake.states.append(
        {
            "entity_id": "calendar.vecchio",
            "state": "off",
            "attributes": {"friendly_name": "Vecchio"},
        }
    )
    fake.events["calendar.vecchio"] = [
        stored_event(
            "Dentista",
            f"{today - timedelta(days=5)} 10:00:00",
            f"{today - timedelta(days=5)} 11:00:00",
        ),
        stored_event(
            "Festa",
            f"{today + timedelta(days=10)} 18:00:00",
            f"{today + timedelta(days=10)} 19:00:00",
        ),
    ]
    _open_sources_step(tablet, stack_full)

    card = tablet.locator("fieldset.card", has_text="Importa dai vecchi calendari")
    expect(card).to_be_visible(timeout=3000)
    card.get_by_label("Calendario da importare").select_option("calendar.vecchio")
    card.get_by_role("button", name="Anteprima").click()
    expect(card.locator(".import-list li")).to_have_count(2)
    expect(tablet.locator("p.hint", has_text="2 eventi da copiare")).to_be_visible()

    card.get_by_role("button", name="Importa", exact=True).click()
    expect(tablet.locator("#status-note")).to_contain_text("Importati 2 eventi", timeout=3000)
    added = [c for c in fake.calls if c["service"] == "add_event"]
    assert len(added) == 2

    card.get_by_role("button", name="Anteprima").click()
    expect(tablet.locator("p.hint", has_text="Nessun evento da copiare")).to_be_visible()
    assert len([c for c in fake.calls if c["service"] == "add_event"]) == 2
