"""0.8.0b1: repeating events from the form. A new event that repeats sends its rule; a change to one
that repeats asks which occurrences it reaches; a delete asks too; the windows fit the screen in
light and dark, in Italian, German and English."""

from __future__ import annotations

from datetime import date

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_layout_071_e2e import _open
from tests.e2e.test_tablet import _device
from tests.fake_ha import FAMILY, stored_event

TUESDAY_RULE = "FREQ=WEEKLY;BYDAY=TU;COUNT=4"


def _calls(stack: Stack, service: str) -> list[dict[str, object]]:
    return [c["data"] for c in stack.fake.calls if c["service"] == service]


def _seed_repeating(stack: Stack, summary: str) -> None:
    today = date.today().isoformat()
    record = stored_event(summary, f"{today} 10:00:00", f"{today} 11:00:00", "mamma")
    stack.fake.events[FAMILY].append({**record, "rrule": TUESDAY_RULE})


def _tap(page: Page, summary: str) -> None:
    page.locator(".event", has_text=summary).click()
    expect(page.locator("#card-overlay")).to_be_visible(timeout=3000)


def _fill_new(page: Page, summary: str, day: str) -> None:
    page.locator("#add-btn").click()
    form = page.locator("#event-form")
    expect(form).to_be_visible(timeout=3000)
    form.locator("input[name='summary']").fill(summary)
    form.locator("input[name='date']").fill(day)


def test_a_new_event_that_repeats_sends_its_rule(stack_full: Stack, browser: Browser) -> None:
    stack_full.fake.calls.clear()
    with _device(browser, 390, 844) as page:
        _open(page, stack_full)
        _fill_new(page, "Visita", "03/11/2026")
        form = page.locator("#event-form")
        form.locator("#repeat-kind").select_option("weekly")
        form.locator("#repeat-end").select_option("count")
        form.locator("#repeat-count").fill("4")
        form.locator(".dialog-foot .btn-primary").click()
        expect(page.locator("#event-overlay")).to_be_hidden(timeout=3000)
    added = _calls(stack_full, "add_event")
    assert added and added[-1]["rrule"] == TUESDAY_RULE, added[-1:]


def test_the_second_Monday_of_the_month_sends_its_rule(stack_full: Stack, browser: Browser) -> None:
    stack_full.fake.calls.clear()
    with _device(browser, 1024, 768) as page:
        _open(page, stack_full)
        _fill_new(page, "Consiglio", "09/11/2026")
        page.locator("#event-form #repeat-kind").select_option("monthly_nth")
        page.locator("#event-form .dialog-foot .btn-primary").click()
        expect(page.locator("#event-overlay")).to_be_hidden(timeout=3000)
    added = _calls(stack_full, "add_event")
    assert added[-1]["rrule"] == "FREQ=MONTHLY;BYDAY=2MO", added[-1:]


def test_changing_one_occurrence_asks_which_ones_and_sends_the_choice(
    stack_full: Stack, browser: Browser
) -> None:
    stack_full.fake.calls.clear()
    _seed_repeating(stack_full, "Visita da cambiare")
    with _device(browser, 390, 844) as page:
        _open(page, stack_full)
        _tap(page, "Visita da cambiare")
        page.locator("#card-foot .btn-primary").click()
        form = page.locator("#event-form")
        expect(form).to_be_visible(timeout=3000)
        expect(page.locator("#event-scope")).to_be_visible()
        page.locator("#event-scope input[value='THISANDFUTURE']").check()
        form.locator("input[name='summary']").fill("Visita di controllo")
        form.locator(".dialog-foot .btn-primary").click()
        expect(page.locator("#event-overlay")).to_be_hidden(timeout=3000)
    updated = _calls(stack_full, "update_event")
    assert updated[-1]["recurrence_range"] == "THISANDFUTURE", updated[-1:]
    assert "rrule" not in updated[-1], "the repeat was not changed"


def test_deleting_a_repeating_event_asks_which_occurrences(
    stack_full: Stack, browser: Browser
) -> None:
    stack_full.fake.calls.clear()
    _seed_repeating(stack_full, "Visita da togliere")
    with _device(browser, 390, 844) as page:
        _open(page, stack_full)
        _tap(page, "Visita da togliere")
        page.locator("#card-foot button").nth(1).click()
        scope = page.locator("#scope-overlay")
        expect(scope).to_be_visible(timeout=3000)
        scope.locator("#scope-all").click()
        expect(scope).to_be_hidden()
    deleted = _calls(stack_full, "delete_event")
    assert deleted[-1]["recurrence_range"] == "ALL", deleted[-1:]


@pytest.mark.parametrize(("width", "height"), [(320, 640), (390, 844), (1024, 768)])
@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("language", ["it", "de", "en"])
def test_the_repeat_windows_fit_the_screen(
    stack_full: Stack, browser: Browser, width: int, height: int, theme: str, language: str
) -> None:
    stack_full.fake.config["screen"] = {**stack_full.fake.config.get("screen", {}), "theme": theme}
    stack_full.fake.config["family"] = {
        **stack_full.fake.config.get("family", {}),
        "language": language,
    }
    _seed_repeating(stack_full, "Visita di prova")
    try:
        with _device(browser, width, height) as page:
            _open(page, stack_full)
            _tap(page, "Visita di prova")
            page.locator("#card-foot .btn-primary").click()
            expect(page.locator("#event-repeat")).to_be_visible(timeout=3000)
            form_box = page.locator("#event-form").bounding_box()
            assert form_box is not None and form_box["x"] >= 0
            assert form_box["x"] + form_box["width"] <= width + 1, form_box
            foot_box = page.locator("#event-form .dialog-foot").bounding_box()
            assert foot_box is not None and foot_box["y"] + foot_box["height"] <= height + 1, (
                foot_box
            )
            page.locator("#event-overlay").evaluate("el => el.scrollTop = 0")
            page.locator("#event-cancel").click()
            _tap(page, "Visita di prova")
            page.locator("#card-foot button").nth(1).click()
            scope = page.locator("#scope-overlay .dialog")
            expect(scope).to_be_visible(timeout=3000)
            scope_box = scope.bounding_box()
            assert scope_box is not None and scope_box["x"] >= 0
            assert scope_box["x"] + scope_box["width"] <= width + 1, scope_box
    finally:
        stack_full.fake.config["screen"] = {
            **stack_full.fake.config.get("screen", {}),
            "theme": "auto",
        }
        stack_full.fake.config["family"] = {
            **stack_full.fake.config.get("family", {}),
            "language": "it",
        }
