"""The "Prossimi ritiri" row under the top bar: one chip per pickup of the next seven days, with
the type's icon and label and "oggi" / "domani" / "tra N giorni", as the TrashCard shows them.
A Home Assistant calendar marked as rubbish counts too."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from playwright.sync_api import Page, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_external_e2e import _add_rubbish_calendar, _remove_rubbish_calendar
from tests.e2e.test_tablet import _shot
from tests.fake_ha import WASTE


def _pickup(summary: str, day: date) -> dict[str, Any]:
    return {
        "summary": summary,
        "start": day.isoformat(),
        "end": (day + timedelta(days=1)).isoformat(),
        "location": "",
        "record_id": "",
        "shift_id": "",
        "person_ids": "",
    }


def test_next_pickups_row_shows_label_icon_and_when(stack_full: Stack, tablet: Page) -> None:
    today = date.today()
    key = "calendar.family_hub_ext_ritiri"
    _add_rubbish_calendar(
        stack_full,
        key,
        "ritiri",
        [
            _pickup("Abfuhr: Bioabfall", today),
            _pickup("Abfuhr: Papierabfall", today + timedelta(days=1)),
            _pickup("Abfuhr: Gelbe Tonne", today + timedelta(days=3)),
            _pickup("Abfuhr: Restabfall", today + timedelta(days=12)),  # too far: not shown
        ],
    )
    try:
        tablet.goto(stack_full.url + "/?lang=it")
        row = tablet.locator("#pickups")
        expect(row).to_be_visible(timeout=5000)
        expect(row).to_contain_text("Prossimi ritiri")
        chips = row.locator(".pickup-chip")
        expect(chips).to_have_count(3)
        expect(chips.nth(0)).to_contain_text("Organico")
        expect(chips.nth(0)).to_contain_text("oggi")
        expect(chips.nth(1)).to_contain_text("Carta")
        expect(chips.nth(1)).to_contain_text("domani")
        expect(chips.nth(2)).to_contain_text("Plastica")
        expect(chips.nth(2)).to_contain_text("tra 3 giorni")
        for i in range(3):
            expect(chips.nth(i).locator(".waste-icon.mdi svg path")).to_have_count(1)
        # The week shows the label too, not the raw title.
        expect(tablet.locator(".event.allday", has_text="Organico")).to_be_visible()
        expect(tablet.locator(".event.allday", has_text="Abfuhr: Bioabfall")).to_have_count(0)
        _shot(tablet, "tablet_next_pickups")
    finally:
        _remove_rubbish_calendar(stack_full, key, "ritiri")


def test_a_home_assistant_rubbish_calendar_feeds_the_row(stack_full: Stack, tablet: Page) -> None:
    today = date.today()
    styles = stack_full.fake.config["sources"].setdefault("calendar_styles", {})
    styles[WASTE] = {"name": "Rifiuti", "type": "rifiuti", "color": "#64748B"}
    old = stack_full.fake.events.get(WASTE, [])
    stack_full.fake.events[WASTE] = [_pickup("Abfuhr: Papierabfall", today + timedelta(days=2))]
    try:
        tablet.goto(stack_full.url + "/?lang=it")
        chip = tablet.locator("#pickups .pickup-chip", has_text="Carta")
        expect(chip).to_be_visible(timeout=5000)
        expect(chip).to_contain_text("tra 2 giorni")
    finally:
        styles.pop(WASTE, None)
        stack_full.fake.events[WASTE] = old
