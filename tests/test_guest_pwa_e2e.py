"""End to end: the grandmother's phone and the guest web app, against a real Home Assistant.

Home Assistant (test instance, real HTTP server on 127.0.0.1) and a Chromium phone (390×844,
Android user agent, touch) run on the same event loop. The adults' side is the websocket API
that the tablet add-on uses.

Needs Playwright's Chromium (python -m playwright install chromium-headless-shell). Without it
the test is skipped, and says so.
"""

from __future__ import annotations

import os
from datetime import timedelta
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.family_hub import webpush
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


def _day(offset: int) -> str:
    return (dt_util.now().date() + timedelta(days=offset)).isoformat()


@pytest.fixture
def expected_lingering_tasks() -> bool:
    return True  # Playwright's own pipes


@pytest.fixture
def expected_lingering_timers() -> bool:
    return True


@pytest.mark.parametrize("expected_lingering_tasks", [True])
async def test_grandmothers_phone_from_invite_to_approved_appointment(
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
                {"id": "mamma", "name": "Mamma Segreta", "color": "#123456", "role": "adult"},
            ],
            OPT_CATEGORIES: [
                {"id": "scuola", "name": "Scuola", "color": "#10B981"},
                {"id": "lavoro", "name": "Lavoro riservato", "color": "#654321"},
            ],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    for category, persons, summary in (
        ("scuola", ["sofia"], "Recita di Sofia"),
        ("lavoro", ["mamma"], "Cena di lavoro"),
    ):
        await hass.services.async_call(
            DOMAIN,
            "add_event",
            {
                "category": category,
                "summary": summary,
                "persons": persons,
                "start": f"{_day(1)} 10:00:00",
                "end": f"{_day(1)} 11:00:00",
            },
            blocking=True,
        )
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
            "approval": "approve",
            "notify": True,
        },
    )
    token = created["link"].split("#i=", 1)[1]
    client = await hass_client_no_auth()
    base = str(client.make_url("/")).rstrip("/")

    async with playwright_api.async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
        except Exception as err:  # noqa: BLE001
            pytest.skip(f"Chromium for Playwright is not installed: {err}")
        try:
            context = await browser.new_context(
                viewport=PHONE,
                user_agent=ANDROID,
                is_mobile=True,
                has_touch=True,
                locale="it-IT",
                timezone_id="Europe/Rome",
            )
            # Headless Chromium refuses notifications by default; a phone asks. The app itself
            # never asks on its own: only the button does.
            await context.grant_permissions(["notifications"])
            page = await context.new_page()
            page.set_default_timeout(TIMEOUT)
            await page.goto(f"{base}/api/family_hub/guest/#i={token}")

            # Android: the invite is used at once; the welcome page explains how to install.
            await page.wait_for_selector("#screen-install:not([hidden])")
            assert "Installa app" in await page.inner_text("#install-android")
            assert "#i=" not in page.url  # the invite left the address bar
            await page.click("#install-continue")

            # Waiting until an adult confirms.
            await page.wait_for_selector("text=In attesa della conferma della famiglia")
            (device,) = (await admin("list"))["devices"]
            assert device["label"] == "Android · Chrome" and device["status"] == "pending"
            await admin("device_confirm", device_id=device["id"], accept=True)

            # The list: only Sofia's school appointment, never the adult's work dinner.
            await page.wait_for_selector("text=Recita di Sofia", timeout=TIMEOUT)
            body = await page.inner_text("body")
            assert "Cena di lavoro" not in body and "Mamma" not in body
            assert "Ciao, Nonna Èlia" in body

            # A new appointment, waiting for approval.
            await page.click("#add-button")
            await page.fill("#f-title", "Merenda dalla nonna")
            await page.click('[data-name="category"] [data-value="scuola"]')
            await page.fill("#f-date", _day(2))
            await page.fill("#f-start", "16:00")
            await page.fill("#f-end", "17:00")
            await page.click("#f-save")
            await page.wait_for_selector("text=Inviato. La famiglia lo deve approvare.")
            card = page.locator(".event", has_text="Merenda dalla nonna")
            await card.wait_for()
            assert "In attesa" in await card.inner_text()

            # The adult approves it in Family Hub; the phone shows it as a normal appointment.
            (pending,) = (await admin("list"))["pending"]
            await admin("pending_decide", pending_id=pending["id"], accept=True)
            await page.click("#tab-week")
            await page.click("#tab-list")
            card = page.locator(".event", has_text="Merenda dalla nonna")
            await page.wait_for_function(
                "() => [...document.querySelectorAll('.event')].some(e => "
                "e.innerText.includes('Merenda dalla nonna') && !e.innerText.includes('In attesa'))"
            )
            assert "aggiunto da Nonna Èlia" in await card.inner_text()
            assert any(
                r.get("added_by", {}).get("name") == "Nonna Èlia"
                for r in entry.runtime_data.store.events.values()
            )

            # Installable: a valid manifest and a service worker for the app's scope.
            manifest = await page.evaluate(
                "fetch(document.querySelector('link[rel=manifest]').href).then(r => r.json())"
            )
            assert manifest["display"] == "standalone" and manifest["start_url"].endswith("/guest/")
            scope = await page.evaluate("navigator.serviceWorker.ready.then(r => r.scope)")
            assert scope.endswith("/api/family_hub/guest/")
            # Nothing wider than the phone.
            width = await page.evaluate("document.documentElement.scrollWidth")
            assert width <= PHONE["width"]
            # The notification button is there (notifications are on in this invite).
            # Headless Chromium keeps notifications blocked even when granted; then the app must
            # say so instead of offering the button.
            permission = await page.evaluate("Notification.permission")
            if permission == "denied":
                assert "bloccate" in await page.inner_text("#push-box")
            else:
                assert await page.is_visible("#push-on")

            # Offline: the last copy, with the notice.
            await context.set_offline(True)
            await page.click("#tab-week")
            await page.click("#tab-list")
            await page.wait_for_selector("text=Non aggiornato – senza connessione")
            # The list's own last copy, also right after switching back from the week (which,
            # on a Sunday, does not have tomorrow's appointment).
            assert "Recita di Sofia" in await page.inner_text("#days")
            await context.set_offline(False)

            # Turned off by an adult: the open app says so at once when it looks again.
            await admin(
                "invite_create",
                invite={"name": "Nonno", "persons": ["sofia"], "categories": ["scuola"]},
            )
            await admin("device_disable", device_id=device["id"])
            await page.evaluate("window.dispatchEvent(new Event('online'))")
            await page.wait_for_selector("text=Accesso disattivato")
            assert "Recita di Sofia" not in await page.inner_text("body")
            assert await page.evaluate("localStorage.getItem('fh_guest_cache')") is None
        finally:
            await browser.close()


def test_web_push_keys_are_valid_p256() -> None:
    keys = webpush.generate_keys()
    assert len(keys["public"]) == 87 and len(keys["private"]) == 43
    assert os.environ.get("FH_NO_SUCH_VAR") is None
