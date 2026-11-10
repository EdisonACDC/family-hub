"""0.7.6: the calendars window on a phone is a sheet as tall as its content, with its own opaque
surface, a veil behind it, and the bottom bar and the + hidden while it is open."""

from __future__ import annotations

import pytest
from playwright.sync_api import Browser, expect

from tests.e2e.conftest import Stack
from tests.e2e.test_layout_071_e2e import _open
from tests.e2e.test_tablet import _device


@pytest.mark.parametrize(("width", "height"), [(320, 640), (360, 780), (390, 844)])
def test_the_calendars_sheet_fits_its_content_and_covers_the_bar(
    stack_full: Stack, browser: Browser, width: int, height: int
) -> None:
    with _device(browser, width, height) as page:
        _open(page, stack_full)
        page.locator("#menu-btn").click()
        page.locator("#menu-calendars").click()
        panel = page.locator("#filters")
        expect(panel).to_be_visible(timeout=3000)
        box = panel.bounding_box()
        assert box is not None
        content = panel.evaluate("el => el.scrollHeight")
        assert box["height"] <= content + 120, (box, content)
        assert box["y"] + box["height"] <= height + 1, box
        # The bar and the + are not there while the window is open.
        assert page.locator("#tabbar").is_hidden()
        assert page.locator("#add-btn").is_hidden()
        # The window is opaque, and a veil darkens the rest of the screen behind it.
        background = panel.evaluate("el => getComputedStyle(el).backgroundColor")
        assert background.startswith("rgb(") and not background.startswith("rgba("), background
        veil = page.evaluate("getComputedStyle(document.body, '::after').backgroundColor")
        assert veil not in ("rgba(0, 0, 0, 0)", "transparent"), veil
