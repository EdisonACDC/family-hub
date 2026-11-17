"""End to end, 0.10.0b2: "Completa" is the panel of Home Assistant itself (the same page, script
and style), fed by the guests' API only. Against a real Home Assistant and a Chromium phone and
tablet: top bar, views, person pills (only the allowed persons), rubbish pills, weather, lists,
the event card, the menu with only what is allowed; never a person, an appointment or a list
that is not allowed, in the page or in what it receives. Names are invented."""

from __future__ import annotations

import contextlib
import os
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
TABLET = {"width": 1180, "height": 820}
ANDROID = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Mobile Safari/537.36"
)
TIMEOUT = 20_000
SHOP = "todo.spesa_esempio"
SECRET_LIST = "todo.lavori_adulti"
SCHOOL = "calendar.istituto_esempio"
OFFICE = "calendar.ufficio_riservato"


@pytest.fixture
def expected_lingering_timers() -> bool:
    return True


def _todo(hass: HomeAssistant) -> dict[str, list[dict[str, str]]]:
    lists = {
        SHOP: [{"uid": "u1", "summary": "Latte", "status": "needs_action"}],
        SECRET_LIST: [{"uid": "s1", "summary": "SEGRETO-LISTA", "status": "needs_action"}],
    }

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

    async def forecasts(call: ServiceCall) -> dict[str, Any]:
        today = dt_util.now().date()
        return {
            "weather.casa_esempio": {
                "forecast": [
                    {
                        "datetime": f"{(today + timedelta(days=i)).isoformat()}T12:00:00+00:00",
                        "condition": "rainy" if i == 1 else "sunny",
                        "temperature": 20 + i,
                        "templow": 10 + i,
                    }
                    for i in range(7)
                ]
            }
        }

    hass.services.async_register(
        "todo", "get_items", get_items, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register("todo", "add_item", add_item)
    hass.services.async_register("todo", "update_item", update_item)
    hass.services.async_register(
        "weather", "get_forecasts", forecasts, supports_response=SupportsResponse.ONLY
    )
    tomorrow = (dt_util.now().date() + timedelta(days=1)).isoformat()

    async def calendar_events(call: ServiceCall) -> dict[str, Any]:
        entity = _entity(call)
        title = "Gita scolastica" if entity == SCHOOL else "UFFICIO-RISERVATO"
        return {
            entity: {
                "events": [
                    {
                        "summary": title,
                        "start": f"{tomorrow}T08:30:00+01:00",
                        "end": f"{tomorrow}T12:30:00+01:00",
                    }
                ]
            }
        }

    hass.services.async_register(
        "calendar", "get_events", calendar_events, supports_response=SupportsResponse.ONLY
    )
    hass.states.async_set(SCHOOL, "off", {"friendly_name": "Istituto Esempio"})
    hass.states.async_set(OFFICE, "off", {"friendly_name": "Ufficio Riservato"})
    hass.states.async_set(SHOP, "1", {"friendly_name": "Spesa"})
    hass.states.async_set(SECRET_LIST, "1", {"friendly_name": "Lavori adulti"})
    return lists


@pytest.mark.parametrize("expected_lingering_tasks", [True])
async def test_full_mode_is_the_panel(
    hass: HomeAssistant, hass_client_no_auth: Any, hass_ws_client: Any, socket_enabled: Any
) -> None:
    assert await async_setup_component(hass, "http", {})
    await hass.config.async_set_time_zone("Europe/Rome")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
        options={
            CONF_LANGUAGE: "it",
            "theme": "dark",
            OPT_PERSONS: [
                {"id": "sofia", "name": "Sofia", "color": "#F97316", "role": "child"},
                {"id": "luca", "name": "Luca", "color": "#0EA5E9", "role": "child"},
                {"id": "mamma", "name": "Mamma Riservata", "color": "#123456", "role": "adult"},
            ],
            OPT_CATEGORIES: [
                {"id": "famiglia", "name": "Famiglia", "color": "#10B981"},
                {"id": "lavoro", "name": "Lavoro Riservato", "color": "#111111"},
            ],
            "sources": {
                "todo": [SHOP, SECRET_LIST],
                "calendars": [SCHOOL, OFFICE],
                "calendar_styles": {
                    SCHOOL: {"type": "altro", "color": "#0EA5E9", "persons": []},
                    OFFICE: {"type": "altro", "persons": []},
                },
                "weather": ["weather.casa_esempio"],
            },
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
    for summary, persons, category in (
        ("Pediatra", ["sofia"], "famiglia"),
        ("Calcio", ["luca"], "famiglia"),
        ("SOLO-MAMMA", ["mamma"], "famiglia"),
        ("RIUNIONE-RISERVATA", ["sofia"], "lavoro"),
    ):
        await hass.services.async_call(
            DOMAIN,
            "add_event",
            {
                "category": category,
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
            "externals": [SCHOOL],
        },
    )
    reader = await admin(
        "invite_create",
        invite={
            "name": "Vicina",
            "persons": ["sofia"],
            "categories": ["famiglia"],
            "template": "custom",
            "mode": "full",
        },
    )
    client = await hass_client_no_auth()
    base = str(client.make_url("/")).rstrip("/") + "/api/family_hub/guest/"
    external = entry.runtime_data.external
    assert external is not None

    async def names_on(source: dict[str, Any], day: date) -> list[str]:
        return ["Carta"] if day == tomorrow else []

    rubbish = [{"id": "r", "type": "rifiuti", "persons": []}]

    async def open_phone(browser: Any, link: str, viewport: dict[str, int]) -> Any:
        context = await browser.new_context(
            viewport=viewport,
            user_agent=ANDROID,
            is_mobile=viewport is PHONE,
            has_touch=True,
            locale="it-IT",
            timezone_id="Europe/Rome",
        )
        page = await context.new_page()
        page.set_default_timeout(TIMEOUT)
        problems: list[str] = []
        received: list[str] = []
        page.on("pageerror", lambda err: problems.append(str(err)))
        page.on(
            "console",
            # A 409 is the refusal of a change on an old version, which one step asks for.
            lambda msg: (
                problems.append(msg.text) if msg.type == "error" and "409" not in msg.text else None
            ),
        )

        async def keep(response: Any) -> None:
            if "/api/family_hub/guest/api/" in response.url:
                with contextlib.suppress(Exception):  # a body that is gone
                    received.append(await response.text())

        page.on("response", keep)
        await page.goto(f"{base}#i={link.split('#i=', 1)[1]}")
        await page.click("#install-continue")
        await page.wait_for_selector("text=In attesa della conferma della famiglia")
        device = next(d for d in (await admin("list"))["devices"] if d["status"] == "pending")
        await admin("device_confirm", device_id=device["id"], accept=True)
        await hass.async_block_till_done()
        return page, device["id"], problems, received

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
                # ----- tablet: the panel's layout -----
                page, device_id, problems, received = await open_phone(
                    browser, relative["link"], TABLET
                )
                await page.wait_for_url("**/full.html", timeout=TIMEOUT)
                await page.wait_for_selector("#topbar")
                # The family's theme, and the panel's own style and page.
                assert await page.get_attribute("html", "data-theme") == "dark"
                await page.wait_for_selector("#clock-time:not(:has-text('--:--'))")
                await page.wait_for_selector("#weather-now:not([hidden])")
                assert "21" in await page.inner_text("#weather-now")
                await page.wait_for_selector("#week .event:has-text('Pediatra')")
                await page.wait_for_selector("#week .event:has-text('Calcio')")
                # The external calendar allowed to this guest, read only.
                await page.wait_for_selector("#week .event:has-text('Gita scolastica')")
                await page.click("#week .event:has-text('Gita scolastica')")
                await page.wait_for_selector("#card-overlay:not([hidden])")
                assert await page.locator("#card-foot button").count() == 1  # only "Chiudi"
                await page.click("#card-foot button")
                # Person pills: everyone, and only the allowed persons.
                pills = await page.locator("#persons-bar .person-chip").all_inner_texts()
                assert [p.strip().lower() for p in pills] == ["tutti", "sofia", "luca"]
                # Rubbish pills.
                await page.wait_for_selector("#pickups .pickup-chip:has-text('Carta')")
                if os.environ.get("FH_SHOTS"):
                    await page.screenshot(path=os.environ["FH_SHOTS"] + "/tablet.png")
                # "+ Nuovo" (may add), "Liste" (allowed).
                assert await page.locator("#add-btn").is_visible()
                assert await page.locator("#todo-btn").is_visible()
                # The menu: only what is allowed.
                await page.click("#menu-btn")
                for hidden in ("menu-share", "menu-wizard", "menu-ics", "menu-notify"):
                    assert await page.locator(f"#{hidden}").is_hidden(), hidden
                assert await page.locator("#menu-shifts").is_hidden()
                assert await page.locator("#menu-transparency").count() == 1
                # 0.10.0b3: the menu closes with a tap outside, Esc, a view change, an event.
                await page.click("#clock-time")
                await page.wait_for_selector("#menu", state="hidden")
                await page.click("#menu-btn")
                await page.keyboard.press("Escape")
                await page.wait_for_selector("#menu", state="hidden")
                await page.click("#menu-btn")
                await page.click("#view-switch [data-view='list']")
                await page.wait_for_selector("#menu", state="hidden")
                await page.click("#view-switch [data-view='week']")
                await page.click("#menu-btn")
                await page.click("#week .event:has-text('Pediatra')")
                await page.wait_for_selector("#card-overlay:not([hidden])")
                assert await page.locator("#menu").is_hidden()
                await page.click("#card-foot button")
                await page.click("#menu-btn")
                await page.click("#add-btn")
                await page.wait_for_selector("#event-overlay:not([hidden])")
                assert await page.locator("#menu").is_hidden()
                await page.click("#event-cancel")
                # Views: Mese and Elenco, with the arrows.
                await page.click("#view-switch [data-view='month']")
                await page.wait_for_selector(".month-scroll, #month-scroll")
                await page.click("#view-switch [data-view='list']")
                await page.wait_for_selector("#week .list-row:has-text('Pediatra')")
                await page.click("#view-switch [data-view='week']")
                # The event card: its own appointments only can be changed.
                await page.click("#week .event:has-text('Pediatra')")
                await page.wait_for_selector("#card-overlay:not([hidden])")
                assert "Sofia" in await page.inner_text("#card-body")
                assert await page.locator("#card-foot button").count() == 1  # only "Chiudi"
                await page.click("#card-foot button")
                # A new appointment of its own, then changed from its card.
                await page.click("#add-btn")
                await page.wait_for_selector("#event-overlay:not([hidden])")
                assert await page.locator("#event-repeat").is_hidden()
                await page.fill("#event-form input[name='summary']", "Merenda")
                await page.fill("#event-form input[name='date']", tomorrow.strftime("%d/%m/%Y"))
                await page.fill("#event-form input[name='start_time']", "10:00")
                await page.fill("#event-form input[name='end_time']", "11:00")
                await page.locator("#event-persons label", has_text="Sofia").click()
                await page.click("#event-form button[type='submit']")
                await page.wait_for_selector("#event-overlay", state="hidden")
                await page.wait_for_selector("#week .event:has-text('Merenda')")
                await page.click("#week .event:has-text('Merenda')")
                await page.wait_for_selector("#card-foot button:has-text('Modifica')")
                # Changed from its card: the version it read goes with the change (0.10.3).
                await page.click("#card-foot button:has-text('Modifica')")
                await page.fill("#event-form input[name='summary']", "Merenda dai nonni")
                await page.click("#event-form button[type='submit']")
                await page.wait_for_selector("#event-overlay", state="hidden")
                await page.wait_for_selector("#week .event:has-text('Merenda dai nonni')")
                # Someone else changes it; the next change from this phone is refused and told.
                await page.click("#week .event:has-text('Merenda dai nonni')")
                await page.click("#card-foot button:has-text('Modifica')")
                merenda = next(
                    r
                    for r in entry.runtime_data.store.events.values()
                    if r["summary"] == "Merenda dai nonni"
                )
                await hass.services.async_call(
                    DOMAIN,
                    "update_event",
                    {"uid": merenda["uid"], "summary": "Cambiata da un adulto"},
                    blocking=True,
                )
                await page.fill("#event-form input[name='summary']", "La mia modifica")
                await page.click("#event-form button[type='submit']")
                await page.wait_for_selector("#event-error:has-text('modificato da qualcun altro')")
                assert merenda["summary"] == "Cambiata da un adulto"
                await page.click("#event-cancel")
                # The lists: add and tick.
                await page.click("#todo-btn")
                await page.wait_for_selector("#todo-overlay:not([hidden])")
                await page.wait_for_selector("#todos-body :text('Latte')")
                await page.locator("#todos-body input[type='text']").fill("Pane")
                await page.locator("#todos-body input[type='text']").press("Enter")
                await page.wait_for_selector("#todos-body :text('Pane')")
                await page.locator("#todos-body input[type='checkbox']").first.check()
                await hass.async_block_till_done()
                assert lists[SHOP][0]["status"] == "completed"
                assert [i["summary"] for i in lists[SHOP]] == ["Latte", "Pane"]
                # Nothing that is not allowed, in the page or in what it received.
                everything = await page.content() + "".join(received)
                for secret in (
                    "SOLO-MAMMA",
                    "Mamma",
                    "RIUNIONE-RISERVATA",
                    "Lavoro Riservato",
                    "SEGRETO-LISTA",
                    "Lavori adulti",
                    "UFFICIO-RISERVATO",
                    "Ufficio Riservato",
                    "calendar.istituto",
                    "todo.",
                    "calendar.family_hub",
                ):
                    assert secret not in everything, secret
                assert problems == []

                # The adult turns the lists off: gone at the next look.
                await admin(
                    "device_update", device_id=device_id, changes={"features": {"lists": False}}
                )
                await page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
                await page.wait_for_selector("#todo-btn", state="hidden")
                # ... and back to Semplice: the simple web app.
                await admin("device_update", device_id=device_id, changes={"mode": "simple"})
                await page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
                await page.wait_for_selector("#screen-main:not([hidden])")
                assert not page.url.endswith("full.html")
                await page.context.close()

                # ----- phone, read only: no "+ Nuovo", no lists, no changes -----
                page2, _, problems2, _ = await open_phone(browser, reader["link"], PHONE)
                await page2.wait_for_url("**/full.html", timeout=TIMEOUT)
                await page2.wait_for_selector("#tabbar")
                await page2.wait_for_selector(".event:has-text('Pediatra')")
                if os.environ.get("FH_SHOTS"):
                    await page2.screenshot(path=os.environ["FH_SHOTS"] + "/phone.png")
                assert await page2.locator(".event:has-text('Calcio')").count() == 0
                assert await page2.locator("#add-btn").is_hidden()
                assert await page2.locator("#tabbar [data-tab='lists']").is_hidden()
                await page2.click(".event:has-text('Pediatra')")
                await page2.wait_for_selector("#card-overlay:not([hidden])")
                assert await page2.locator("#card-foot button").count() == 1
                # The page fits the phone: no sideways scrolling of the page.
                width = await page2.evaluate("document.documentElement.scrollWidth")
                assert width <= PHONE["width"] + 1
                assert problems2 == []
            finally:
                await browser.close()


@pytest.mark.parametrize("expected_lingering_tasks", [True])
async def test_full_mode_without_calendar_stays_simple(
    hass: HomeAssistant, hass_client_no_auth: Any, hass_ws_client: Any, socket_enabled: Any
) -> None:
    """Completa without the calendar: the simple web app says so (the panel would be empty)."""
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it"},
        options={
            CONF_LANGUAGE: "it",
            OPT_PERSONS: [{"id": "sofia", "name": "Sofia", "color": "#F97316", "role": "child"}],
            OPT_CATEGORIES: [{"id": "famiglia", "name": "Famiglia", "color": "#10B981"}],
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

    invite = await admin(
        "invite_create",
        invite={
            "name": "Vicina",
            "persons": ["sofia"],
            "categories": ["famiglia"],
            "template": "custom",
            "mode": "full",
            "features": {"calendar": False},
        },
    )
    client = await hass_client_no_auth()
    base = str(client.make_url("/")).rstrip("/") + "/api/family_hub/guest/"
    async with playwright_api.async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
        except Exception as err:  # noqa: BLE001
            pytest.skip(f"Chromium for Playwright is not installed: {err}")
        try:
            page = await browser.new_page(viewport=PHONE, locale="it-IT")
            page.set_default_timeout(TIMEOUT)
            await page.goto(f"{base}#i={invite['link'].split('#i=', 1)[1]}")
            await page.click("#install-continue")
            await page.wait_for_selector("text=In attesa della conferma della famiglia")
            device = next(d for d in (await admin("list"))["devices"] if d["status"] == "pending")
            await admin("device_confirm", device_id=device["id"], accept=True)
            await page.wait_for_selector("#no-calendar:not([hidden])")
            assert not page.url.endswith("full.html")
        finally:
            await browser.close()


@pytest.mark.parametrize("expected_lingering_tasks", [True])
async def test_full_mode_shifts_board_from_the_menu(
    hass: HomeAssistant, hass_client_no_auth: Any, hass_ws_client: Any, socket_enabled: Any
) -> None:
    """A guest with its own shifts: "Turni" in the menu opens the panel's board, for its own
    person only; what it saves and puts on days lands in its shifts calendar."""
    assert await async_setup_component(hass, "http", {})
    await hass.config.async_set_time_zone("Europe/Rome")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it"},
        options={
            CONF_LANGUAGE: "it",
            OPT_PERSONS: [{"id": "sofia", "name": "Sofia", "color": "#F97316", "role": "child"}],
            OPT_CATEGORIES: [{"id": "famiglia", "name": "Famiglia", "color": "#10B981"}],
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

    invite = await admin(
        "invite_create",
        invite={
            "name": "Nonna Turni",
            "persons": ["sofia"],
            "categories": ["famiglia"],
            "template": "relative",
            "has_shifts": True,
            "shifts_category": "famiglia",
        },
    )
    client = await hass_client_no_auth()
    base = str(client.make_url("/")).rstrip("/") + "/api/family_hub/guest/"
    tomorrow = dt_util.now().date() + timedelta(days=1)
    async with playwright_api.async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
        except Exception as err:  # noqa: BLE001
            pytest.skip(f"Chromium for Playwright is not installed: {err}")
        try:
            page = await browser.new_page(
                viewport=TABLET, locale="it-IT", timezone_id="Europe/Rome"
            )
            page.set_default_timeout(TIMEOUT)
            errors: list[str] = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            await page.goto(f"{base}#i={invite['link'].split('#i=', 1)[1]}")
            await page.click("#install-continue")
            await page.wait_for_selector("text=In attesa della conferma della famiglia")
            device = next(d for d in (await admin("list"))["devices"] if d["status"] == "pending")
            await admin("device_confirm", device_id=device["id"], accept=True)
            await page.wait_for_url("**/full.html", timeout=TIMEOUT)
            await page.click("#menu-btn")
            await page.click("#menu-shifts")
            await page.wait_for_selector("#shifts-overlay:not([hidden])")
            await page.click("#shifts-models button:has-text('Aggiungi turno')")
            await page.locator("#shifts-models .shift-row input").first.fill("Mattina")
            await page.click("#shifts-models button:has-text('Salva turni')")
            await page.wait_for_function(
                "() => !document.querySelector('#shifts-models .shift-row input')"
                " || document.querySelector('#shifts-models .shift-row input').value === 'Mattina'"
            )
            await hass.async_block_till_done()
            device_now = next(
                d for d in (await admin("list"))["devices"] if d["id"] == device["id"]
            )
            person = device_now["person_id"]
            shifts = entry.options["shifts"][person]
            assert [s["name"] for s in shifts] == ["Mattina"]
            await page.click("#tab-calendar")
            await page.wait_for_selector("#shifts-calendar .day-cell")
            if tomorrow.month != dt_util.now().date().month:
                await page.click("#shifts-calendar .month-nav button:has-text('→')")
            await page.locator("#shifts-calendar select").select_option(label="Mattina")
            await page.click(f"#shifts-calendar .day-cell:has(.dnum:text-is('{tomorrow.day}'))")
            await page.click("#shifts-calendar button:has-text('Applica')")
            await page.wait_for_selector(
                f"#shifts-calendar .day-cell:has(.dnum:text-is('{tomorrow.day}')) .dshift"
            )
            assert errors == []
        finally:
            await browser.close()


@pytest.mark.parametrize("expected_lingering_tasks", [True])
async def test_guest_web_apps_fit_every_width(
    hass: HomeAssistant, hass_client_no_auth: Any, hass_ws_client: Any, socket_enabled: Any
) -> None:
    """The guests' web app, Simple and Completa, at 360, 390, 430, 768 and 1024 px: nothing sticks
    out of the screen, "+ Nuovo" and the menu are always there, and the new-appointment window
    fits."""
    assert await async_setup_component(hass, "http", {})
    await hass.config.async_set_time_zone("Europe/Rome")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
        options={
            CONF_LANGUAGE: "it",
            OPT_PERSONS: [
                {
                    "id": "sofia",
                    "name": "Sofia Alessandra Maria",
                    "color": "#F97316",
                    "role": "child",
                },
                {
                    "id": "luca",
                    "name": "Luca Giovanni Battista",
                    "color": "#0EA5E9",
                    "role": "child",
                },
                {
                    "id": "anna",
                    "name": "Anna Costanza Valentina",
                    "color": "#10B981",
                    "role": "adult",
                },
            ],
            OPT_CATEGORIES: [{"id": "famiglia", "name": "Famiglia", "color": "#10B981"}],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    tomorrow = dt_util.now().date() + timedelta(days=1)
    await hass.services.async_call(
        DOMAIN,
        "add_event",
        {
            "category": "famiglia",
            "summary": "Visita dal pediatra con un titolo molto lungo da andare a capo",
            "persons": ["sofia"],
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

    invites = {
        "completa": await admin(
            "invite_create",
            invite={
                "name": "Zia Èlia",
                "persons": ["sofia", "luca", "anna"],
                "categories": ["famiglia"],
                "template": "relative",
            },
        ),
        "semplice": await admin(
            "invite_create",
            invite={
                "name": "Nonna",
                "persons": ["sofia", "luca"],
                "categories": ["famiglia"],
                "template": "grandparents",
            },
        ),
    }
    client = await hass_client_no_auth()
    base = str(client.make_url("/")).rstrip("/") + "/api/family_hub/guest/"
    widths = [360, 390, 430, 768, 1024]
    async with playwright_api.async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
        except Exception as err:  # noqa: BLE001
            pytest.skip(f"Chromium for Playwright is not installed: {err}")
        try:
            for kind, invite in invites.items():
                context = await browser.new_context(
                    viewport={"width": 390, "height": 800},
                    user_agent=ANDROID,
                    is_mobile=True,
                    has_touch=True,
                    locale="it-IT",
                    timezone_id="Europe/Rome",
                )
                page = await context.new_page()
                page.set_default_timeout(TIMEOUT)
                problems: list[str] = []
                page.on("pageerror", lambda err, found=problems: found.append(str(err)))
                await page.goto(f"{base}#i={invite['link'].split('#i=', 1)[1]}")
                await page.click("#install-continue")
                await page.wait_for_selector("text=In attesa della conferma della famiglia")
                device = next(
                    d for d in (await admin("list"))["devices"] if d["status"] == "pending"
                )
                await admin("device_confirm", device_id=device["id"], accept=True)
                await hass.async_block_till_done()
                for width in widths:
                    await page.set_viewport_size({"width": width, "height": 800})
                    await page.goto(base)
                    if kind == "completa":
                        await page.wait_for_url("**/full.html")
                        await page.wait_for_selector("#week .event, #week .list-row, #week .day")
                        add, menu = "#add-btn", "#menu-btn"
                    else:
                        await page.wait_for_selector("#screen-main:not([hidden])")
                        await page.wait_for_selector(".event")
                        add, menu = "#add-button", None
                    for selector in (add, menu):
                        if selector is None:
                            continue
                        box = await page.locator(selector).first.bounding_box()
                        assert box is not None, (kind, width, selector)
                        assert box["x"] >= 0 and box["x"] + box["width"] <= width + 1, (
                            kind,
                            width,
                            selector,
                        )
                    scroll = await page.evaluate("document.documentElement.scrollWidth")
                    assert scroll <= width, (kind, width, scroll)
                    # The window to add an appointment fits too.
                    await page.click(add)
                    sheet = "#event-form" if kind == "completa" else "#sheet"
                    await page.wait_for_selector(sheet)
                    wide = await page.evaluate(
                        """(sel) => {
                          const box = document.querySelector(sel).getBoundingClientRect();
                          const bad = [];
                          if (box.right > window.innerWidth + 1) bad.push("outside the screen");
                          for (const el of document.querySelectorAll(sel + " *")) {
                            const r = el.getBoundingClientRect();
                            if (r.width && r.right > box.right + 1 && !el.closest("[hidden]")) {
                              const name = el.id || el.className || el.tagName;
                              bad.push(name + " " + Math.round(r.right));
                            }
                          }
                          return bad.slice(0, 5);
                        }""",
                        sheet,
                    )
                    assert wide == [], (kind, width, wide)
                    await page.keyboard.press("Escape")
                assert problems == [], (kind, problems)
                await context.close()
        finally:
            await browser.close()
