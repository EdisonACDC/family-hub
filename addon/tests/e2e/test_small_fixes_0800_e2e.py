"""0.8.0b1: a rubbish name in a narrow week column is never broken in the middle of a word; the date
under the time is drawn in the new language at once when a language is left unsaved."""

from __future__ import annotations

import re
from datetime import date

from playwright.sync_api import Page, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_pickups_e2e import _add_rubbish_calendar, _pickup, _remove_rubbish_calendar


def test_a_long_rubbish_name_is_not_broken_inside_a_word(stack_full: Stack, tablet: Page) -> None:
    today = date.today()
    key = "calendar.family_hub_ext_schnitt"
    _add_rubbish_calendar(stack_full, key, "schnitt", [_pickup("Abfuhr: Indifferenziato", today)])
    try:
        tablet.goto(stack_full.url + "/?lang=it")
        pill = tablet.locator(".event.waste-pill[aria-label='Indifferenziato']")
        expect(pill).to_be_visible(timeout=5000)
        # A narrow place: the word does not fit, so it is cut with an ellipsis, never broken.
        tablet.add_style_tag(
            content=".event.waste-pill .ev-title, .event.waste-pill .allday-name"
            " { max-width: 24px !important; overflow: hidden; white-space: nowrap; }"
        )
        tablet.evaluate("window.dispatchEvent(new Event('resize'))")
        name = pill.locator(".allday-name, .ev-title").first
        expect(name).to_have_text(re.compile(r"…$"), timeout=5000)
        text = name.evaluate("el => el.textContent.trim()")
        assert text.endswith("…") and "Indifferenziato".startswith(text[:-1]), text
        style = name.evaluate(
            "el => ({hyphens: getComputedStyle(el).hyphens,"
            " wrap: getComputedStyle(el).overflowWrap})"
        )
        assert style == {"hyphens": "none", "wrap": "normal"}, style
    finally:
        _remove_rubbish_calendar(stack_full, key, "schnitt")


def test_the_date_under_the_time_changes_language_at_once(
    stack_empty: Stack, admin_tablet: Page
) -> None:
    stack_empty.fake.config["configured"] = False  # the guide opens by itself
    tablet = admin_tablet
    tablet.goto(stack_empty.url + "/?lang=it")
    expect(tablet.locator("#wizard-overlay")).to_be_visible(timeout=3000)
    before = tablet.locator("#clock-date").text_content()
    tablet.get_by_label("Lingua").select_option("en")
    expect(tablet.locator("#clock-date")).not_to_have_text(before or "", timeout=2000)
    after = tablet.locator("#clock-date").text_content()
    assert after and after != before
    tablet.keyboard.press("Escape")
    tablet.locator("#wizard-leave-exit").click()
    expect(tablet.locator("#wizard-overlay")).to_be_hidden()
    assert tablet.locator("#clock-date").text_content() == before
