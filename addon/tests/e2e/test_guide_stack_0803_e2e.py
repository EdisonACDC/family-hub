"""0.8.0b3: a repeating event's card says its repeat in one line (it, de, en); the delete
choice does not highlight "Tutti"; the windows opened from the guide's sources step stay on top
of it, and closing them returns to the same step."""

from __future__ import annotations

import re
from datetime import date

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_layout_071_e2e import _open
from tests.e2e.test_tablet import _device
from tests.fake_ha import FAMILY, stored_event


def _seed(stack: Stack, summary: str, rule: str) -> None:
    today = date.today().isoformat()
    record = stored_event(summary, f"{today} 10:00:00", f"{today} 11:00:00", "mamma")
    stack.fake.events[FAMILY].append({**record, "rrule": rule})


def _tap(page: Page, summary: str) -> None:
    page.locator(".event", has_text=summary).click()
    expect(page.locator("#card-overlay")).to_be_visible(timeout=3000)


@pytest.mark.parametrize(
    ("language", "text"),
    [
        ("it", "Ogni giovedì · 4 volte"),
        ("de", "Jeden Donnerstag · 4 Mal"),
        ("en", "Every Thursday · 4 times"),
    ],
)
def test_the_card_says_the_repeat_in_one_line(
    stack_full: Stack, browser: Browser, language: str, text: str
) -> None:
    stack_full.fake.config["family"] = {
        **stack_full.fake.config.get("family", {}),
        "language": language,
    }
    _seed(stack_full, "Ripetizione di prova", "FREQ=WEEKLY;BYDAY=TH;COUNT=4")
    try:
        with _device(browser, 390, 844) as page:
            _open(page, stack_full)
            _tap(page, "Ripetizione di prova")
            expect(page.locator("#card-body .card-repeat")).to_have_text(text, timeout=3000)
    finally:
        stack_full.fake.events[FAMILY] = [
            e for e in stack_full.fake.events[FAMILY] if e.get("summary") != "Ripetizione di prova"
        ]
        stack_full.fake.config["family"] = {
            **stack_full.fake.config.get("family", {}),
            "language": "it",
        }


def test_the_delete_choice_does_not_highlight_all(stack_full: Stack, browser: Browser) -> None:
    _seed(stack_full, "Da eliminare", "FREQ=WEEKLY;BYDAY=TU;COUNT=4")
    with _device(browser, 390, 844) as page:
        _open(page, stack_full)
        _tap(page, "Da eliminare")
        page.locator("#card-foot button").nth(1).click()
        expect(page.locator("#scope-overlay")).to_be_visible(timeout=3000)
        assert "btn-primary" not in (page.locator("#scope-all").get_attribute("class") or "")
        assert "btn-primary" in (page.locator("#scope-this").get_attribute("class") or "")
        page.locator("#scope-cancel").click()
    stack_full.fake.events[FAMILY] = [
        e for e in stack_full.fake.events[FAMILY] if e.get("summary") != "Da eliminare"
    ]


def _guide_to_sources(page: Page, stack: Stack) -> None:
    stack.fake.config["configured"] = False  # the guide opens by itself
    page.goto(stack.url + "/?lang=it")
    expect(page.locator("#wizard-overlay")).to_be_visible(timeout=3000)
    for _ in range(4):
        page.locator("#wizard-skip").click()
    expect(page.locator("#wizard-progress")).to_have_text(re.compile(r"5 \D+ 6\s*$"))


def _top_is(page: Page, selector: str) -> bool:
    return page.evaluate(
        "sel => { const el = document.elementFromPoint(innerWidth / 2, innerHeight / 2);"
        " return !!(el && el.closest(sel)); }",
        selector,
    )


@pytest.mark.parametrize(("width", "height"), [(390, 844), (1024, 768)])
def test_the_windows_opened_from_the_guide_are_on_top_and_return_to_its_step(
    stack_empty: Stack, admin_tablet: Page, width: int, height: int
) -> None:
    stack_empty.fake.config["configured"] = False
    try:
        page = admin_tablet
        page.set_viewport_size({"width": width, "height": height})
        if True:
            _guide_to_sources(page, stack_empty)
            # "Crea a mano": the pickups window is on top, usable, and closing returns to step 5.
            page.locator("#wizard-body button", has_text="Crea a mano").click()
            expect(page.locator("#manual-overlay")).to_be_visible(timeout=3000)
            assert _top_is(page, "#manual-overlay")
            page.locator("#manual-cancel").click()
            expect(page.locator("#manual-overlay")).to_be_hidden()
            expect(page.locator("#wizard-progress")).to_have_text(re.compile(r"5 \D+ 6\s*$"))
            # "Calendari esterni": the same.
            page.locator("#wizard-body button", has_text="Calendari esterni").click()
            expect(page.locator("#ics-overlay")).to_be_visible(timeout=3000)
            assert _top_is(page, "#ics-overlay")
            page.locator("#ics-close").click()
            expect(page.locator("#ics-overlay")).to_be_hidden()
            expect(page.locator("#wizard-progress")).to_have_text(re.compile(r"5 \D+ 6\s*$"))
    finally:
        stack_empty.fake.config["configured"] = False
