"""0.7.2: a holiday shows on each of its days (and its card says how long it lasts), and an
appointment takes the colour of its person (several persons: several dots)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta

from playwright.sync_api import Locator, Page, expect

from tests.e2e.conftest import Stack
from tests.fake_ha import FAMILY, WASTE, stored_event

MAMMA = "#2563eb"
SOFIA = "#e91e63"


@contextmanager
def _holiday_and_appointments(stack: Stack) -> Iterator[None]:
    today = date.today()
    # Five days, from tomorrow: the end is the day after the last one (as in Home Assistant).
    holiday = stored_event(
        "Vacanze di prova",
        (today + timedelta(days=1)).isoformat(),
        (today + timedelta(days=6)).isoformat(),
    )
    solo = stored_event("Solo Mamma", f"{today} 09:00:00", f"{today} 10:00:00", "mamma")
    duo = stored_event("Insieme", f"{today} 11:00:00", f"{today} 12:00:00", "mamma,sofia")
    family = stored_event("Di tutti", f"{today} 19:00:00", f"{today} 20:00:00", "")
    stack.fake.events[FAMILY].extend([solo, duo, family])
    stack.fake.events[WASTE] = [holiday]
    styles = stack.fake.config["sources"].setdefault("calendar_styles", {})
    styles[WASTE] = {"name": "Ferien", "type": "vacanze_scuola", "color": "#0EA5E9", "persons": []}
    try:
        yield
    finally:
        for event in (solo, duo, family):
            stack.fake.events[FAMILY].remove(event)
        stack.fake.events[WASTE] = []
        styles.pop(WASTE, None)


def _open(page: Page, stack: Stack) -> None:
    page.add_init_script(
        "try { localStorage.removeItem('fh_view'); localStorage.removeItem('fh_person'); }"
        " catch (e) {}"
    )
    page.goto(stack.url + "/?lang=it")
    expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)


def _colour(locator: Locator) -> str:
    return str(locator.evaluate("e => e.style.getPropertyValue('--ev')")).strip().lower()


def test_a_holiday_is_listed_on_each_of_its_days_and_its_card_says_how_long(
    stack_full: Stack, tablet: Page
) -> None:
    with _holiday_and_appointments(stack_full):
        _open(tablet, stack_full)
        tablet.locator("#view-switch [data-view='list']").click()
        rows = tablet.locator("#list-scroll .list-row", has_text="Vacanze di prova")
        expect(rows).to_have_count(5, timeout=5000)
        rows.first.click()
        card = tablet.locator("#card-overlay")
        expect(card).to_be_visible(timeout=3000)
        expect(card).to_contain_text("5 giorni")


def test_a_holiday_is_a_light_band_in_the_month(stack_full: Stack, tablet: Page) -> None:
    with _holiday_and_appointments(stack_full):
        _open(tablet, stack_full)
        tablet.locator("#view-switch [data-view='month']").click()
        bands = tablet.locator(".month-ev.holiday", has_text="Vacanze di prova")
        expect(bands.first).to_be_attached(timeout=5000)
        # A band, not a filled cell: its background is the light one.
        background = bands.first.evaluate("e => getComputedStyle(e).backgroundColor")
        assert background == "rgba(255, 255, 255, 0.1)", background


def test_an_appointment_has_the_colour_of_its_person(stack_full: Stack, tablet: Page) -> None:
    with _holiday_and_appointments(stack_full):
        _open(tablet, stack_full)
        tablet.locator("#view-switch [data-view='month']").click()
        line = tablet.locator(".month-ev", has_text="Solo Mamma").first
        expect(line).to_be_attached(timeout=5000)
        assert _colour(line) == MAMMA


def test_two_persons_show_two_dots_and_a_person_colour(stack_full: Stack, tablet: Page) -> None:
    with _holiday_and_appointments(stack_full):
        _open(tablet, stack_full)
        duo = tablet.locator("#week .event", has_text="Insieme").first
        expect(duo).to_be_visible(timeout=5000)
        expect(duo.locator(".person-dot")).to_have_count(2)
        assert _colour(duo) in {MAMMA, SOFIA}


def test_an_appointment_without_persons_keeps_the_calendar_colour(
    stack_full: Stack, tablet: Page
) -> None:
    with _holiday_and_appointments(stack_full):
        _open(tablet, stack_full)
        family = tablet.locator("#week .event", has_text="Di tutti").first
        expect(family).to_be_visible(timeout=5000)
        expect(family.locator(".person-dot")).to_have_count(0)
        # The calendar's own colour: the first of the palette, which is also Mamma's colour in the
        # fake family, so the test checks the calendar colour and not a person's.
        assert _colour(family) == "#2563eb"
