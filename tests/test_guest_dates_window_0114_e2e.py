"""End to end, 0.11.0b4: in the guest web app the days a guest may not choose are greyed and cannot
be tapped (yesterday and before, and more than two years ahead), in both modes. The simple mode's
card names the dates of a series of chosen dates, and its month title stays on one line.

Needs Playwright's Chromium. Without it the tests are skipped, and say so.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from tests.test_guest_chosen_dates_e2e import (  # noqa: F401  (the helpers of that file)
    TIMEOUT,
    TITLE,
    _create_two_dates,
    _dates,
    _open_phone,
    _setup,
)

playwright_api = pytest.importorskip("playwright.async_api")

FUTURE_DAYS = 731
PAST_DAYS = 1


def _greyed(today: date) -> list[bool]:
    """For each day of today's month: True when a guest may not choose it."""
    first_allowed = today - timedelta(days=PAST_DAYS)
    last_allowed = today + timedelta(days=FUTURE_DAYS)
    next_month = date(today.year + (today.month // 12), today.month % 12 + 1, 1)
    days = (next_month - date(today.year, today.month, 1)).days
    return [
        not (first_allowed <= date(today.year, today.month, n) <= last_allowed)
        for n in range(1, days + 1)
    ]


async def _check_greyed(cells: Any, expected: list[bool]) -> None:
    # The calendar is drawn after the click: wait until every day of the month is there.
    await playwright_api.expect(cells).to_have_count(len(expected), timeout=TIMEOUT)
    assert await cells.count() == len(expected), "one button for every day of the month"
    for index, grey in enumerate(expected):
        assert await cells.nth(index).is_disabled() is grey, f"day {index + 1} greyed={grey}"


def _short(day: date) -> str:
    """The day and the month as the Dutch-style "dd/mm" the app shows in Italian."""
    return f"{day.day:02d}/{day.month:02d}"


async def test_simple_mode_greys_the_days_a_guest_may_not_choose(
    hass: HomeAssistant, hass_client_no_auth: Any, hass_ws_client: Any, socket_enabled: Any
) -> None:
    admin, link, base = await _setup(hass, hass_client_no_auth, hass_ws_client, "simple")
    today = dt_util.now().date()
    async with playwright_api.async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
        except Exception as err:  # noqa: BLE001
            pytest.skip(f"Chromium for Playwright is not installed: {err}")
        try:
            page, _ = await _open_phone(hass, browser, base, link, admin)
            await page.wait_for_selector("#add-button:not([hidden])", timeout=TIMEOUT)
            await page.click("#add-button")
            await page.check("#f-chosen")
            await _check_greyed(page.locator("#sheet .chosen-day"), _greyed(today))
            # The date field of an ordinary appointment has the same limits.
            assert (
                await page.get_attribute("#f-date", "min")
                == (today - timedelta(days=PAST_DAYS)).isoformat()
            )
            assert (
                await page.get_attribute("#f-date", "max")
                == (today + timedelta(days=FUTURE_DAYS)).isoformat()
            )
        finally:
            await browser.close()


async def test_full_mode_greys_the_days_a_guest_may_not_choose_in_the_calendar(
    hass: HomeAssistant, hass_client_no_auth: Any, hass_ws_client: Any, socket_enabled: Any
) -> None:
    admin, link, base = await _setup(hass, hass_client_no_auth, hass_ws_client, "full")
    today = dt_util.now().date()
    async with playwright_api.async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
        except Exception as err:  # noqa: BLE001
            pytest.skip(f"Chromium for Playwright is not installed: {err}")
        try:
            page, _ = await _open_phone(hass, browser, base, link, admin)
            await page.wait_for_url("**/full.html", timeout=TIMEOUT)
            await page.click("#add-btn")
            await page.select_option("#repeat-kind", "chosen")
            await _check_greyed(page.locator("#chosen-box .chosen-grid .day-cell"), _greyed(today))
        finally:
            await browser.close()


async def test_full_mode_greys_the_days_in_the_date_picker(
    hass: HomeAssistant, hass_client_no_auth: Any, hass_ws_client: Any, socket_enabled: Any
) -> None:
    admin, link, base = await _setup(hass, hass_client_no_auth, hass_ws_client, "full")
    today = dt_util.now().date()
    async with playwright_api.async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
        except Exception as err:  # noqa: BLE001
            pytest.skip(f"Chromium for Playwright is not installed: {err}")
        try:
            page, _ = await _open_phone(hass, browser, base, link, admin)
            await page.wait_for_url("**/full.html", timeout=TIMEOUT)
            await page.click("#add-btn")
            await page.click("#event-form input[name='date']")
            await _check_greyed(page.locator(".datepick .day-cell"), _greyed(today))
        finally:
            await browser.close()


async def test_simple_mode_card_names_the_dates_of_a_series(
    hass: HomeAssistant, hass_client_no_auth: Any, hass_ws_client: Any, socket_enabled: Any
) -> None:
    admin, link, base = await _setup(hass, hass_client_no_auth, hass_ws_client, "simple")
    today = dt_util.now().date()
    first, second = _dates(today)
    async with playwright_api.async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
        except Exception as err:  # noqa: BLE001
            pytest.skip(f"Chromium for Playwright is not installed: {err}")
        try:
            page, _ = await _open_phone(hass, browser, base, link, admin)
            await page.wait_for_selector("#add-button:not([hidden])", timeout=TIMEOUT)
            await page.click("#add-button")
            await page.check("#f-chosen")
            await page.fill("#f-title", TITLE)
            await _create_two_dates(
                page, "#sheet .chosen-picker", (".chosen-day", ".month-num"), today, first, second
            )
            # The month's title is one line: its box is no taller than a line of text.
            title_box = await page.locator("#sheet .chosen-month").bounding_box()
            assert title_box and title_box["height"] < 40, title_box
            await page.click("#f-save")
            await page.wait_for_selector("#sheet", state="hidden", timeout=TIMEOUT)
            await hass.async_block_till_done()
            await page.click(f".event:has-text('{TITLE}') >> nth=0")
            await page.wait_for_selector("#sheet .chosen-line", timeout=TIMEOUT)
            expected = f"Date scelte: {_short(first)}, {_short(second)} (2 date)"
            assert (await page.inner_text("#sheet .chosen-line")) == expected
        finally:
            await browser.close()
