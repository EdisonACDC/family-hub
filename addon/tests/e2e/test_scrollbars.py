"""Scrollbars: thin and translucent in the windows and panels; solid grey with "Riduci
trasparenza"; and the stylesheet never forces a bar with overflow: scroll."""

from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import Page, expect

from tests.e2e.conftest import Stack

CSS = Path(__file__).resolve().parents[2] / "app" / "static" / "app.css"


def test_dialog_scrollbar_is_thin(stack_full: Stack, tablet: Page) -> None:
    tablet.goto(stack_full.url + "/?lang=it")
    expect(tablet.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
    tablet.locator("#menu-btn").click()
    tablet.locator("#menu-notify").click()
    expect(tablet.locator("#notify-overlay .dialog")).to_be_visible()
    expect(tablet.locator("#notify-overlay .dialog")).to_have_css("scrollbar-width", "thin")


def test_reduce_transparency_makes_the_scrollbar_grey(stack_full: Stack, tablet: Page) -> None:
    tablet.goto(stack_full.url + "/?lang=it")
    expect(tablet.locator("body[data-ready='1']")).to_be_attached(timeout=5000)
    tablet.locator("#menu-btn").click()
    tablet.locator("#menu .switch-row").first.click()
    expect(tablet.locator("body")).to_have_class("reduce-transparency")
    tablet.locator("#menu-notify").click()
    expect(tablet.locator("#notify-overlay .dialog")).to_have_css(
        "scrollbar-color", "rgb(142, 142, 147) rgba(0, 0, 0, 0)"
    )


def test_no_rule_forces_a_scrollbar() -> None:
    css = CSS.read_text(encoding="utf-8")
    assert not re.search(r"overflow(-x|-y)?:\s*scroll\b", css)
