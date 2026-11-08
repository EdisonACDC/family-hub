"""Every text key that app.js asks for exists in Italian, German and English.

A missing key does not crash: the page quietly shows the English text, or the key name itself.
This test reads the keys app.js uses (t("...") for the interface table, f("...") or I.f("...")
for the form table) and checks each language's tables in a real page.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from playwright.sync_api import Browser, expect

from tests.e2e.conftest import Stack, tablet_as
from tests.helpers import ADULT_USER

APP_JS = Path(__file__).resolve().parents[2] / "app" / "static" / "app.js"

# t("key") and t(cond ? "a" : "b") use the interface table; f(...) and I.f(...) the form table.
UI_CALL = re.compile(r"(?<![\w.])t\(([^()]*)\)")
FORM_CALL = re.compile(r"(?:(?<![\w.])f|I\.f)\(([^()]*)\)")
KEY = re.compile(r'"(\w+)"')


def _keys_used(source: str) -> tuple[set[str], set[str]]:
    ui = {k for args in UI_CALL.findall(source) for k in KEY.findall(args)}
    form = {k for args in FORM_CALL.findall(source) for k in KEY.findall(args)}
    return ui, form


def test_the_scan_finds_the_keys_it_should() -> None:
    ui, form = _keys_used(APP_JS.read_text(encoding="utf-8"))
    assert "newEvent" in form and "editEvent" in form
    assert "sharedTitle" in form or "moreCalendars" in form
    assert len(ui) > 20 and len(form) > 50


@pytest.mark.parametrize("lang", ["it", "de", "en"])
def test_every_key_app_js_uses_exists_in_the_language(
    stack_full: Stack, browser: Browser, lang: str
) -> None:
    ui_used, form_used = _keys_used(APP_JS.read_text(encoding="utf-8"))
    with tablet_as(browser, ADULT_USER) as page:
        page.goto(stack_full.url + f"/?lang={lang}")
        expect(page.locator(".chip").first).to_be_visible(timeout=5000)
        ui_have = set(page.evaluate("window.FH_I18N.keys('ui')"))
        form_have = set(page.evaluate("window.FH_I18N.keys('form')"))
    assert sorted(ui_used - ui_have) == [], f"interface keys missing in {lang}"
    assert sorted(form_used - form_have) == [], f"form keys missing in {lang}"
