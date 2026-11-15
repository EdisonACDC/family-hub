"""End to end, 0.10: the "Familiare" phone in Completa mode (month, person filter, lists,
rubbish days, weather) and a phone with the calendar turned off, against a real Home Assistant
and a Chromium phone. What the adult turns off disappears from the phone and answers 403.
Names are invented."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
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
    "Chrome/130.0.0.0 Mobile Safari/537.36"
)
TIMEOUT = 20_000
SHOP = "todo.spesa_esempio"


@pytest.fixture
def expected_lingering_timers() -> bool:
    return True


def _todo(hass: HomeAssistant) -> dict[str, list[dict[str, str]]]:
    lists = {SHOP: [{"uid": "u1", "summary": "Latte", "status": "needs_action"}]}

    def _entity(call: ServiceCall) -> str:
        entity = call.data["entity_id"]
        return str(entity[0] if isinstance(entity, list) else entity)

    async def get_items(call: ServiceCall) -> dict[str, Any]:
        return {_entity(call): {"items": lists[_entity(call)]}}

    async def add_item(call: ServiceCall) -> None:
        items = lists[_entity(call)]
        items.append(
            {"uid": f"n{len(items)}", "summary": call.data["item"], "status": "needs_action"}
        )

    async def update_item(call: ServiceCall) -> None:
        for item in lists[_entity(call)]:
            if item["uid"] == call.data["item"]:
                item["status"] = call.data["status"]

    hass.services.async_register(
        "todo", "get_items", get_items, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register("todo", "add_item", add_item)
    hass.services.async_register("todo", "update_item", update_item)
    hass.states.async_set(SHOP, "1", {"friendly_name": "Spesa"})
    return lists


@pytest.mark.parametrize("expected_lingering_tasks", [True])
async def test_full_mode_with_lists_rubbish_and_weather(
    hass: HomeAssistant, hass_client_no_auth: Any, hass_ws_client: Any, socket_enabled: Any
) -> None:
    assert await async_setup_component(hass, "http", {})
    await hass.config.async_set_time_zone("Europe/Rome")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
        options={
            CONF_LANGUAGE: "it",
            OPT_PERSONS: [
                {"id": "sofia", "name": "Sofia", "color": "#F97316", "role": "child"},
                {"id": "luca", "name": "Luca", "color": "#0EA5E9", "role": "child"},
                {"id": "mamma", "name": "Mamma Riservata", "color": "#123456", "role": "adult"},
            ],
            OPT_CATEGORIES: [{"id": "famiglia", "name": "Famiglia", "color": "#10B981"}],
            "sources": {"todo": [SHOP], "calendars": [], "weather": ["weather.casa_esempio"]},
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    lists = _todo(hass)
    hass.states.async_set(
        "weather.casa_esempio", "sunny", {"temperature": 21, "temperature_unit": "°C"}
    )
    tomorrow = dt_util.now().date() + timedelta(days=1)
    for summary, persons in (
        ("Pediatra", ["sofia"]),
        ("Calcio", ["luca"]),
        ("SOLO-MAMMA", ["mamma"]),
    ):
        await hass.services.async_call(
            DOMAIN,
            "add_event",
            {
                "category": "famiglia",
                "summary": summary,
                "persons": persons,
                "start": f"{tomorrow.isoformat()} 16:00:00",
                "end": f"{tomorrow.isoformat()} 17:00:00",
            },
            blocking=True,
        )
    ws = await hass_ws_client()

    async def admin(command: str, **data: Any) -> Any:
        await ws.send_json_auto_id({"type": f"family_hub/guest/{command}", **data})
        answer = await ws.receive_json()
        assert answer["success"], answer
        return answer["result"]

    relative = await admin(
        "invite_create",
        invite={
            "name": "Zia Èlia",
            "persons": ["sofia", "luca"],
            "categories": ["famiglia"],
            "template": "relative",
            "features": {"lists": True},
            "lists": [SHOP],
            "lists_edit": True,
        },
    )
    no_calendar = await admin(
        "invite_create",
        invite={
            "name": "Vicina",
            "persons": ["sofia"],
            "categories": ["famiglia"],
            "template": "custom",
            "features": {"calendar": False, "weather": True},
        },
    )
    client = await hass_client_no_auth()
    base = str(client.make_url("/")).rstrip("/") + "/api/family_hub/guest/"
    external = entry.runtime_data.external
    assert external is not None

    async def names_on(source: dict[str, Any], day: date) -> list[str]:
        return ["Carta"] if day == tomorrow else []

    rubbish = [{"id": "r", "type": "rifiuti", "persons": []}]

    async def open_phone(browser: Any, link: str) -> Any:
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
        errors: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        await page.goto(f"{base}#i={link.split('#i=', 1)[1]}")
        await page.click("#install-continue")
        await page.wait_for_selector("text=In attesa della conferma della famiglia")
        device = next(d for d in (await admin("list"))["devices"] if d["status"] == "pending")
        await admin("device_confirm", device_id=device["id"], accept=True)
        await hass.async_block_till_done()
        return page, device["id"], errors

    with (
        patch.object(external, "sources", return_value=rubbish),
        patch.object(external, "_ha_sources", return_value=[]),
        patch.object(external, "_names_on", side_effect=names_on),
    ):
        async with playwright_api.async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=True)
            except Exception as err:  # noqa: BLE001
                pytest.skip(f"Chromium for Playwright is not installed: {err}")
            try:
                page, device_id, errors = await open_phone(browser, relative["link"])
                await page.wait_for_selector("#tab-month:not([hidden])")
                # Completa: smaller letters, weather, the month and the person filter.
                assert await page.evaluate(
                    "document.documentElement.classList.contains('mode-full')"
                )
                await page.wait_for_selector("#weather-line:not([hidden])")
                assert "21" in await page.inner_text("#weather-line")
                await page.wait_for_selector(".event:has-text('Pediatra')")
                await page.wait_for_selector(".event:has-text('Calcio')")
                await page.click("[data-person='luca']")
                await page.wait_for_selector(".event:has-text('Pediatra')", state="detached")
                assert await page.locator(".event:has-text('Calcio')").count() == 1
                await page.click(".filter-chip:has-text('Tutti')")
                await page.wait_for_selector(".event:has-text('Pediatra')")
                await page.click("#tab-month")
                await page.wait_for_selector(".month-grid")
                if tomorrow.month != dt_util.now().date().month:
                    await page.click("#week-next")
                cell = f"[data-month-day='{tomorrow.isoformat()}']"
                await page.wait_for_selector(f"{cell} .month-bar:has-text('Pediatra')")
                await page.click(cell)
                await page.wait_for_selector("#sheet .event:has-text('Calcio')")
                await page.click("#sheet-actions button")
                assert "SOLO-MAMMA" not in await page.content()
                assert "Mamma" not in await page.content()
                # The list: add and tick.
                await page.click("#tool-lists")
                await page.wait_for_selector("[data-item='u1']")
                await page.fill("#list-new", "Pane")
                await page.click("#list-add")
                await page.wait_for_selector(".todo-item:has-text('Pane')")
                await page.click("[data-item='u1'] input")
                await page.wait_for_selector("[data-item='u1'].done")
                assert lists[SHOP][0]["status"] == "completed"
                assert [i["summary"] for i in lists[SHOP]] == ["Latte", "Pane"]
                await page.click("#sheet-actions button:has-text('Chiudi')")
                # Rubbish days.
                await page.click("#tool-waste")
                await page.wait_for_selector(
                    f"[data-waste-day='{tomorrow.isoformat()}']:has-text('Carta')"
                )
                await page.click("#sheet-actions button")
                # The adult turns the lists off: gone from the phone at its next look.
                await admin(
                    "device_update", device_id=device_id, changes={"features": {"lists": False}}
                )
                await page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
                await page.wait_for_selector("#tool-lists", state="hidden")
                assert errors == []

                page2, _, errors2 = await open_phone(browser, no_calendar["link"])
                await page2.wait_for_selector("#no-calendar:not([hidden])")
                assert await page2.locator("#tabs").is_hidden()
                assert await page2.locator("#add-button").is_hidden()
                assert await page2.locator(".event").count() == 0
                await page2.wait_for_selector("#weather-line:not([hidden])")
                assert not await page2.evaluate(
                    "document.documentElement.classList.contains('mode-full')"
                )
                assert errors2 == []
            finally:
                await browser.close()
