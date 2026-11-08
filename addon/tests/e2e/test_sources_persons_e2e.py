"""Home Assistant calendars chosen in Fonti (the family's old calendars, calendar.mamma ...):
they count as busy time, they belong to the persons chosen for them, and an event that is in
more than one calendar is shown once, with a dot for each other calendar."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any

from playwright.sync_api import Page, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_tablet import _shot
from tests.fake_ha import FAMILY, SCHOOL, stored_event

OLD = "calendar.mamma"


def _day() -> date:
    today = date.today()
    return today if today.day < 25 else today - timedelta(days=3)


@contextmanager
def _old_calendar(stack: Stack) -> Iterator[str]:
    fake = stack.fake
    day = _day().isoformat()
    next_day = (_day() + timedelta(days=1)).isoformat()
    config_before = copy.deepcopy(fake.config)
    family_before = list(fake.events[FAMILY])
    school_before = list(fake.events[SCHOOL])
    fake.states.append(
        {"entity_id": OLD, "state": "off", "attributes": {"friendly_name": "Mamma (vecchio)"}}
    )
    fake.config["sources"]["calendars"] = [*fake.config["sources"]["calendars"], OLD]
    fake.config["sources"]["calendar_styles"] = {
        OLD: {"name": "", "type": "altro", "color": "#AA3366", "persons": ["mamma"]}
    }
    holiday = ("Vacanze Autunnali 2026", day, next_day)
    fake.events[OLD] = [
        stored_event("Fisio", f"{day} 09:00:00", f"{day} 10:30:00"),
        stored_event("Visita U11 + vaccini", f"{day} 15:00:00", f"{day} 16:00:00"),
        stored_event(*holiday),
    ]
    fake.events[FAMILY].append(stored_event(*holiday))
    fake.events[SCHOOL].append(stored_event(*holiday))
    try:
        yield day
    finally:
        fake.config = config_before
        fake.events.pop(OLD, None)
        fake.events[FAMILY] = family_before
        fake.events[SCHOOL] = school_before
        fake.states[:] = [s for s in fake.states if s["entity_id"] != OLD]


def _open_month(page: Page, stack: Stack) -> None:
    page.goto(stack.url + "/?lang=it")
    expect(page.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
    phone = (page.viewport_size or {}).get("width", 1024) < 600
    page.locator(
        "#tabbar [data-tab='month']" if phone else "#view-switch [data-view='month']"
    ).click()
    expect(page.locator("#month-scroll")).to_be_visible(timeout=5000)


def test_old_calendars_count_as_busy_and_belong_to_their_person(
    stack_full: Stack, tablet: Page
) -> None:
    with _old_calendar(stack_full) as day:
        _open_month(tablet, stack_full)
        cell = tablet.locator(f".month-day[data-day='{day}']")
        # Fisio 09:00-10:30 and the visit 15:00-16:00: 150 minutes.
        expect(cell).to_have_attribute("data-busy", "150")
        tablet.locator("#persons-bar [data-person='mamma']").click()
        expect(cell).to_have_attribute("data-busy", "150")
        tablet.locator("#persons-bar [data-person='sofia']").click()
        expect(cell).to_have_attribute("data-busy", "0")
        expect(cell.locator(".month-ev", has_text="Fisio")).to_have_count(0)
        tablet.locator("#persons-bar [data-person='']").click()
        cell.click(position={"x": 8, "y": 8})
        busy = tablet.locator(".dayview .busy-block", has_text="Fisio")
        expect(busy).to_be_visible()


def test_an_event_in_three_calendars_is_shown_once_with_dots(
    stack_full: Stack, tablet: Page
) -> None:
    with _old_calendar(stack_full) as day:
        tablet.goto(stack_full.url + "/?lang=it")
        week_day = tablet.locator(f".day[aria-label='{day}']")
        rows = week_day.locator(".event", has_text="Vacanze Autunnali 2026")
        expect(rows).to_have_count(1, timeout=5000)
        expect(rows.first.locator(".cal-dot")).to_have_count(2)
        _shot(tablet, "tablet_shared_event_once")
        tablet.locator("#view-switch [data-view='month']").click()
        cell = tablet.locator(f".month-day[data-day='{day}']")
        expect(cell.locator(".month-ev", has_text="Vacanze Autunnali 2026")).to_have_count(1)
        # Back to the week for the next tests on this screen.
        tablet.locator("#view-switch [data-view='week']").click()


def test_fonti_chooses_the_persons_of_a_home_assistant_calendar(
    stack_full: Stack, tablet: Page
) -> None:
    with _old_calendar(stack_full):
        before = len(stack_full.fake.saved_configs)
        tablet.goto(stack_full.url + "/?lang=it")
        expect(tablet.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
        tablet.locator("#menu-btn").click()
        tablet.locator("#menu-wizard").click()
        for _ in range(4):
            tablet.locator("#wizard-next").click()
        expect(tablet.locator("#wizard-progress")).to_have_text("Passo 5 di 6")
        persons = tablet.locator(
            "label.check:has(input[value='calendar.mamma']) + .cal-style .cal-persons"
        )
        expect(persons).to_be_visible(timeout=5000)
        mamma = persons.locator("label", has_text="Mamma").locator("input")
        expect(mamma).to_be_checked()
        persons.locator("label", has_text="Sofia").click()
        _shot(tablet, "tablet_fonti_persons")
        tablet.locator("#wizard-next").click()
        expect(tablet.locator("#wizard-progress")).to_have_text("Passo 6 di 6")
        tablet.locator("#wizard-next").click()
        expect(tablet.locator("#wizard-overlay")).to_be_hidden(timeout=3000)
        assert len(stack_full.fake.saved_configs) == before + 1
        saved: dict[str, Any] = stack_full.fake.saved_configs[-1]
        assert sorted(saved["sources"]["calendar_styles"][OLD]["persons"]) == ["mamma", "sofia"]
