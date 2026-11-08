"""The "Prossimi ritiri" row under the top bar: one chip per pickup of the next seven days, with
the type's icon and label and "oggi" / "domani" / "tra N giorni", as the TrashCard shows them.
A Home Assistant calendar marked as rubbish counts too."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_external_e2e import _add_rubbish_calendar, _remove_rubbish_calendar
from tests.e2e.test_tablet import _shot
from tests.fake_ha import WASTE
from tests.helpers import ADULT_USER


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


def test_pickups_stay_on_one_line_that_scrolls_on_the_phone(
    stack_full: Stack, browser: Browser
) -> None:
    today = date.today()
    key = "calendar.family_hub_ext_riga"
    titles = ["Abfuhr: Bioabfall", "Abfuhr: Papierabfall", "Abfuhr: Gelbe Tonne"]
    _add_rubbish_calendar(
        stack_full,
        key,
        "riga",
        [_pickup(titles[i % 3], today + timedelta(days=i)) for i in range(6)],
    )
    context = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True)
    context.set_extra_http_headers({"X-Remote-User-Id": ADULT_USER})
    page = context.new_page()
    try:
        page.goto(stack_full.url + "/?lang=it")
        chips = page.locator("#pickups .pickup-chip")
        expect(chips).to_have_count(6, timeout=5000)
        tops = {round(chips.nth(i).bounding_box()["y"]) for i in range(6)}  # type: ignore[index]
        assert len(tops) == 1, tops  # one line, never one under the other
        row = page.locator("#pickups")
        assert row.evaluate("e => e.scrollWidth > e.clientWidth")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        _shot(page, "phone_next_pickups")
    finally:
        context.close()
        _remove_rubbish_calendar(stack_full, key, "riga")


def test_a_type_name_that_does_not_fit_shows_only_the_icon(stack_full: Stack, tablet: Page) -> None:
    today = date.today()
    key = "calendar.family_hub_ext_pillola"
    _add_rubbish_calendar(stack_full, key, "pillola", [_pickup("Abfuhr: Restabfall", today)])
    try:
        tablet.goto(stack_full.url + "/?lang=it")
        pill = tablet.locator(".event.waste-pill[aria-label='Indifferenziato']")
        expect(pill).to_have_class(re.compile(r"\bicon-only\b"), timeout=5000)
        expect(pill.locator(".allday-name")).to_be_hidden()
        icon = pill.locator(".waste-icon").bounding_box()
        assert icon and icon["width"] >= 27
        _shot(tablet, "tablet_icon_only_pill")
        pill.click()
        card = tablet.locator("#card-overlay")
        expect(card.locator(".card-title")).to_have_text("Indifferenziato")
        expect(card.locator(".card-raw")).to_have_text("Abfuhr: Restabfall")
    finally:
        _remove_rubbish_calendar(stack_full, key, "pillola")
