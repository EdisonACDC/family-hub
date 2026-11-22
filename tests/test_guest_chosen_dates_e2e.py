"""End to end, 0.11.0b1: chosen dates in the guest web app, on a phone (390 x 844), in both modes.

A guest with the permission to add appointments picks two dates in two months, each with its own
times, and saves. Then "Tutti" changes the title and keeps each date's times. The adults' side is
the websocket API the tablet add-on uses, and Home Assistant holds the result.

Needs Playwright's Chromium. Without it the test is skipped, and says so.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.family_hub.const import (
    CONF_FAMILY_NAME,
    CONF_FIRST_WEEKDAY,
    CONF_LANGUAGE,
    DOMAIN,
    OPT_CATEGORIES,
    OPT_PERSONS,
)

playwright_api = pytest.importorskip("playwright.async_api")

PHONE = {"width": 390, "height": 844}
ANDROID = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Mobile Safari/537.36"
)
TIMEOUT = 20_000
TITLE = "Recita di Natale"
NEW_TITLE = "Concerto di Natale"


def _months_after(today: date, target: date) -> int:
    return (target.year - today.year) * 12 + (target.month - today.month)


async def _tap_day(page: Any, grid: str, cells: tuple[str, str], day: date, today: date) -> None:
    """Move the month of the picker to the day's month (it opens on today's), then tap the day.
    ``cells`` is the day's button and the number inside it: the simple app and the panel name them
    differently."""
    cell_css, number_css = cells
    for _ in range(max(0, _months_after(today, day))):
        await page.click(f"{grid} >> text=→")
    cell = page.locator(f"{grid} {cell_css}").filter(
        has=page.locator(number_css, has_text=re.compile(rf"^{day.day}$"))
    )
    await cell.first.click()


async def _open_phone(
    hass: HomeAssistant, browser: Any, base: str, link: str, admin: Any
) -> tuple[Any, str]:
    context = await browser.new_context(
        viewport=PHONE,
        user_agent=ANDROID,
        is_mobile=True,
        has_touch=True,
        locale="it-IT",
        timezone_id="Europe/Rome",
    )
    page = await context.new_page()
    page.set_default_timeout(TIMEOUT)
    await page.goto(f"{base}#i={link.split('#i=', 1)[1]}")
    await page.click("#install-continue")
    await page.wait_for_selector("text=In attesa della conferma della famiglia")
    device = next(d for d in (await admin("list"))["devices"] if d["status"] == "pending")
    await admin("device_confirm", device_id=device["id"], accept=True)
    await hass.async_block_till_done()
    return page, device["id"]


def _family_series(hass: HomeAssistant) -> list[dict[str, Any]]:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    return sorted(
        (r for r in entry.runtime_data.store.events.values() if r.get("chosen")),
        key=lambda r: r["start"],
    )


async def _setup(
    hass: HomeAssistant, hass_client_no_auth: Any, hass_ws_client: Any, mode: str
) -> Any:
    assert await async_setup_component(hass, "http", {})
    await hass.config.async_set_time_zone("Europe/Rome")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
        options={
            CONF_LANGUAGE: "it",
            OPT_PERSONS: [
                {"id": "sofia", "name": "Sofia", "color": "#F97316", "role": "child"},
                {"id": "mamma", "name": "Mamma Segreta", "color": "#123456", "role": "adult"},
            ],
            OPT_CATEGORIES: [{"id": "scuola", "name": "Scuola", "color": "#10B981"}],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    ws = await hass_ws_client()

    async def admin(command: str, **data: Any) -> Any:
        await ws.send_json_auto_id({"type": f"family_hub/guest/{command}", **data})
        answer = await ws.receive_json()
        assert answer["success"], answer
        return answer["result"]

    created = await admin(
        "invite_create",
        invite={
            "name": "Nonna Èlia",
            "persons": ["sofia"],
            "categories": ["scuola"],
            "permission": "edit_own",
            "approval": "direct",
            "notify": False,
            "mode": mode,
        },
    )
    client = await hass_client_no_auth()
    base = str(client.make_url("/")).rstrip("/") + "/api/family_hub/guest/"
    return admin, created["link"], base


async def _create_two_dates(
    page: Any, grid: str, cells: tuple[str, str], today: date, first: date, second: date
) -> None:
    """The form of a new appointment with chosen dates: two days, two months, two times."""
    await _tap_day(page, grid, cells, first, today)
    row = page.locator(".chosen-row")
    await row.nth(0).locator(".chosen-start").fill("10:00")
    await row.nth(0).locator(".chosen-start").press("Tab")
    await row.nth(0).locator(".chosen-end").fill("11:00")
    await row.nth(0).locator(".chosen-end").press("Tab")
    await _tap_day(page, grid, cells, second, today)
    await row.nth(1).locator(".chosen-start").fill("18:00")
    await row.nth(1).locator(".chosen-start").press("Tab")
    await row.nth(1).locator(".chosen-end").fill("19:30")
    await row.nth(1).locator(".chosen-end").press("Tab")


def _dates(today: date) -> tuple[date, date]:
    first = today + timedelta(days=1)
    second = today + timedelta(days=40)
    return first, second


async def test_simple_mode_chosen_dates_and_all_on_a_phone(
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
            await page.click("#f-save")
            await page.wait_for_selector("#sheet", state="hidden", timeout=TIMEOUT)
            await hass.async_block_till_done()
            records = _family_series(hass)
            assert [r["start"][11:16] for r in records] == ["10:00", "18:00"], records
            assert [r["end"][11:16] for r in records] == ["11:00", "19:30"], records
            assert len({r["series"] for r in records}) == 1

            # "Tutti" changes the title; the times of each date stay as they were.
            await page.click(f".event:has-text('{TITLE}') >> nth=0")
            await page.click("#sheet button:has-text('Modifica')")
            await page.click("[data-name='scope'] [data-value='ALL']")
            await page.wait_for_selector("#sheet .chosen-row", timeout=TIMEOUT)
            assert await page.locator("#sheet .chosen-row").count() == 2
            await page.fill("#f-title", NEW_TITLE)
            await page.click("#f-save")
            await page.wait_for_selector("#sheet", state="hidden", timeout=TIMEOUT)
            await hass.async_block_till_done()
            changed = _family_series(hass)
            assert [r["summary"] for r in changed] == [NEW_TITLE, NEW_TITLE]
            assert [r["start"][11:16] for r in changed] == ["10:00", "18:00"]
        finally:
            await browser.close()


async def test_full_mode_chosen_dates_and_all_on_a_phone(
    hass: HomeAssistant, hass_client_no_auth: Any, hass_ws_client: Any, socket_enabled: Any
) -> None:
    admin, link, base = await _setup(hass, hass_client_no_auth, hass_ws_client, "full")
    today = dt_util.now().date()
    first, second = _dates(today)
    async with playwright_api.async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
        except Exception as err:  # noqa: BLE001
            pytest.skip(f"Chromium for Playwright is not installed: {err}")
        try:
            page, _ = await _open_phone(hass, browser, base, link, admin)
            await page.wait_for_url("**/full.html", timeout=TIMEOUT)
            await page.click("#add-btn")
            await page.locator("#event-persons label", has_text="Sofia").first.click()
            await page.fill("#event-form input[name='summary']", TITLE)
            await page.select_option("#repeat-kind", "chosen")
            # The date of the form is the first date by itself: it is taken off, the two are picked.
            await page.locator("#chosen-box .day-cell[aria-pressed='true']").first.click()
            await _create_two_dates(
                page, "#chosen-box", (".day-cell", ".dnum"), today, first, second
            )
            await page.click("#event-form .dialog-foot .btn-primary")
            await page.wait_for_timeout(1500)
            assert await page.locator("#event-overlay").is_hidden(), (
                "save: " + await page.inner_text("#event-error")
            )
            await page.wait_for_selector("#event-overlay", state="hidden", timeout=TIMEOUT)
            await hass.async_block_till_done()
            records = _family_series(hass)
            assert [r["start"][11:16] for r in records] == ["10:00", "18:00"], records
            assert [r["end"][11:16] for r in records] == ["11:00", "19:30"], records

            await page.click(f"#week .event:has-text('{TITLE}') >> nth=0")
            await page.click("#card-foot button:has-text('Modifica')")
            await page.check("#event-scope input[name='scope'][value='ALL']")
            await page.wait_for_selector("#chosen-box .chosen-row", timeout=TIMEOUT)
            assert await page.locator("#chosen-box .chosen-row").count() == 2
            await page.fill("#event-form input[name='summary']", NEW_TITLE)
            await page.click("#event-form .dialog-foot .btn-primary")
            await page.wait_for_selector("#event-overlay", state="hidden", timeout=TIMEOUT)
            await hass.async_block_till_done()
            changed = _family_series(hass)
            assert [r["summary"] for r in changed] == [NEW_TITLE, NEW_TITLE]
            assert [r["start"][11:16] for r in changed] == ["10:00", "18:00"]
        finally:
            await browser.close()
