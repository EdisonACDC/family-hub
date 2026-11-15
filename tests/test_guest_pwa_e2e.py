"""End to end: the grandmother's phone and the guest web app, against a real Home Assistant.

Home Assistant (test instance, real HTTP server on 127.0.0.1) and a Chromium phone (390×844,
Android user agent, touch) run on the same event loop. The adults' side is the websocket API
that the tablet add-on uses.

Needs Playwright's Chromium (python -m playwright install chromium-headless-shell). Without it
the test is skipped, and says so.
"""

from __future__ import annotations

import asyncio
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
IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) CriOS/131.0.6778.73 Mobile/15E148 Safari/604.1"
)


# What the web app keeps in its own IndexedDB: the keys, or None when there is no such database.
IDB_KEYS = """() => new Promise(resolve => {
  const request = indexedDB.open('family-hub-guest');
  request.onsuccess = () => {
    const db = request.result;
    if (!db.objectStoreNames.contains('kv')) { resolve([]); return; }
    const keys = db.transaction('kv', 'readonly').objectStore('kv').getAllKeys();
    keys.onsuccess = () => resolve(keys.result.sort());
  };
  request.onerror = () => resolve(null);
})"""
LEGACY = "Object.keys(localStorage).filter(k => k.startsWith('fh_guest_'))"


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

            # The link opened in a browser that is signed in to Home Assistant (an adult looking
            # at it): a warning, and the invite is not spent.
            adult = await browser.new_context(viewport=PHONE, user_agent=ANDROID, locale="it-IT")
            await adult.add_init_script("localStorage.setItem('hassTokens', '{}')")
            adult_page = await adult.new_page()
            adult_page.set_default_timeout(TIMEOUT)
            await adult_page.goto(f"{base}/api/family_hub/guest/#i={token}")
            await adult_page.wait_for_selector("text=Questo link è per il telefono dell'invitato")
            assert await adult_page.is_visible("text=Usalo comunque su questo telefono")
            assert (await admin("list"))["devices"] == []
            assert (await admin("list"))["invites"][0]["status"] == "open"
            await adult.close()

            # An iPhone in the browser (Safari or Chrome): the welcome page explains both, says
            # notifications need the Home Screen icon, and does not spend the invite here.
            iphone = await browser.new_context(viewport=PHONE, user_agent=IPHONE, locale="it-IT")
            iphone_page = await iphone.new_page()
            iphone_page.set_default_timeout(TIMEOUT)
            await iphone_page.goto(f"{base}/api/family_hub/guest/#i={token}")
            await iphone_page.wait_for_selector("#install-ios:not([hidden])")
            steps = await iphone_page.inner_text("#install-ios")
            assert "Safari" in steps and "Chrome" in steps and "16.4" in steps
            assert "barra dell'indirizzo" in steps and "solo così arrivano le notifiche" in steps
            assert "Apri questo link in Safari" not in steps
            assert (await admin("list"))["devices"] == []
            await iphone.close()

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
            # The phone keeps its token in its own IndexedDB, not in localStorage beside
            # Home Assistant's login.
            assert "token" in await page.evaluate(IDB_KEYS)
            assert await page.evaluate(LEGACY) == []

            # The week starts today, as the family's tablet (the default "week from today").
            await page.click("#tab-week")
            await page.wait_for_function(
                "() => (document.querySelector('#days .day h3') || {}).innerText"
                " && document.querySelector('#days .day h3').innerText.startsWith('Oggi')"
            )
            await page.wait_for_selector("#days >> text=Recita di Sofia")
            await page.click("#tab-list")

            # A tapped "new appointment" notification opens that appointment (#e=<id>.<day>).
            recita = next(
                u
                for u, r in entry.runtime_data.store.events.items()
                if r["summary"] == "Recita di Sofia"
            )
            await page.evaluate(f"location.hash = 'e={recita}.{_day(1)}'")
            await page.wait_for_selector("#sheet:not([hidden]) >> text=Recita di Sofia")
            assert "#e=" not in page.url
            await page.click("#sheet-actions >> text=Chiudi")

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
            banner = page.locator("#push-banner")
            if permission == "denied":
                assert "bloccate" in await page.inner_text("#push-box")
                # The strip at the top says so too, and the adults see "Bloccate".
                assert "bloccate" in await banner.inner_text()
                await page.wait_for_function("1")
                for _ in range(20):
                    if (await admin("list"))["devices"][0]["push_status"] == "blocked":
                        break
                    await asyncio.sleep(0.1)
                assert (await admin("list"))["devices"][0]["push_status"] == "blocked"
            else:
                assert "Attiva le notifiche per ricevere i promemoria" in await banner.inner_text()
            # One button only: the strip at the top (none at the foot, under "+ Aggiungi").
            assert await page.locator("#push-on").count() == 0
            # Space at the end: the last appointment is not under "+ Aggiungi".
            last = await page.locator(".event").last.bounding_box()
            add = await page.locator("#add-button").bounding_box()
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            last = await page.locator(".event").last.bounding_box()
            assert last and add and last["y"] + last["height"] <= add["y"]

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
            # Nothing of the family stays: no token, no saved appointments, no subscription;
            # only the note that access ended, so it says so again when reopened.
            await page.wait_for_function(
                IDB_KEYS.replace(
                    "resolve(keys.result.sort())", "resolve(keys.result.sort().join() === 'ended')"
                )
            )
            assert await page.evaluate(IDB_KEYS) == ["ended"]
            assert await page.evaluate(LEGACY) == []
            assert (
                await page.evaluate(
                    "navigator.serviceWorker.ready.then(r => r.pushManager.getSubscription())"
                )
                is None
            )
            await page.reload()
            await page.wait_for_selector("text=Accesso disattivato")

            # The used link opened again on another phone: "not valid", and nothing kept.
            other = await browser.new_context(viewport=PHONE, user_agent=ANDROID, locale="it-IT")
            other_page = await other.new_page()
            other_page.set_default_timeout(TIMEOUT)
            await other_page.goto(f"{base}/api/family_hub/guest/#i={token}")
            await other_page.wait_for_selector("text=Invito non valido")
            assert await other_page.evaluate(IDB_KEYS) == ["ended"]
            await other.close()
            log = (await admin("list"))["log"]
            assert any(e["kind"] == "attempt_used" for e in log)
        finally:
            await browser.close()


def test_web_push_keys_are_valid_p256() -> None:
    keys = webpush.generate_keys()
    assert len(keys["public"]) == 87 and len(keys["private"]) == 43
    assert os.environ.get("FH_NO_SUCH_VAR") is None


@pytest.mark.parametrize("expected_lingering_tasks", [True])
@pytest.mark.parametrize("signed_in", [False, True], ids=["phone", "browser_with_ha_login"])
async def test_a_new_invite_works_on_a_phone_whose_access_ended(
    hass: HomeAssistant,
    hass_client_no_auth: Any,
    hass_ws_client: Any,
    socket_enabled: Any,
    signed_in: bool,
) -> None:
    """A phone turned off, then a new invite opened in the same browser: the new invite is
    followed (HA-login warning first when needed), waits, is confirmed, and shows the calendar.
    The saved "Accesso disattivato" counts only when the app opens without an invite."""
    assert await async_setup_component(hass, "http", {})
    await hass.config.async_set_time_zone("Europe/Rome")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
        options={
            CONF_LANGUAGE: "it",
            OPT_PERSONS: [{"id": "sofia", "name": "Sofia", "color": "#F97316", "role": "child"}],
            OPT_CATEGORIES: [{"id": "scuola", "name": "Scuola", "color": "#10B981"}],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await hass.services.async_call(
        DOMAIN,
        "add_event",
        {
            "category": "scuola",
            "summary": "Recita di Sofia",
            "persons": ["sofia"],
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

    async def invite(name: str) -> str:
        created = await admin(
            "invite_create",
            invite={"name": name, "persons": ["sofia"], "categories": ["scuola"]},
        )
        return str(created["link"].split("#i=", 1)[1])

    async def device_named(name: str) -> dict[str, Any]:
        return next(d for d in (await admin("list"))["devices"] if d["name"] == name)

    await invite("Zia")  # an open invite keeps the web app on throughout
    client = await hass_client_no_auth()
    base = str(client.make_url("/")).rstrip("/") + "/api/family_hub/guest/"

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
            if signed_in:
                await context.add_init_script("localStorage.setItem('hassTokens', '{}')")
            page = await context.new_page()
            page.set_default_timeout(TIMEOUT)
            # No window of the browser may open: the confirmation is in the page.
            page.on("dialog", lambda dialog: pytest.fail(f"browser dialog: {dialog.message}"))

            async def follow_invite(token: str, name: str, *, same_tab: bool) -> None:
                if same_tab:
                    # Only the part after # changes: the page does not load again.
                    await page.evaluate(f"location.hash = 'i={token}'")
                else:
                    await page.goto(f"{base}#i={token}")
                if signed_in:
                    await page.wait_for_selector("text=Questo link è per il telefono dell'invitato")
                    await page.click("text=Usalo comunque su questo telefono")
                    # The question is in the page, not in a window of the browser.
                    await page.wait_for_selector("text=L'invito vale per un solo telefono")
                    await page.click("text=Sì, usalo su questo telefono")
                await page.wait_for_selector("#screen-install:not([hidden])")
                await page.click("#install-continue")
                await page.wait_for_selector("text=In attesa della conferma della famiglia")
                device = await device_named(name)
                assert device["status"] == "pending"
                await admin("device_confirm", device_id=device["id"], accept=True)
                await page.wait_for_selector("#days >> text=Recita di Sofia")
                assert await page.evaluate(IDB_KEYS) == ["cache", "me", "token"]

            # 1. The first phone, then turned off by an adult while the app is not looking.
            await follow_invite(await invite("Nonna"), "Nonna", same_tab=False)
            await admin("device_disable", device_id=(await device_named("Nonna"))["id"])

            # 2. A new invite in the same open tab: the old token is turned off, so it gives way.
            await follow_invite(await invite("Prova b4 A"), "Prova b4 A", same_tab=True)
            assert (await device_named("Nonna"))["status"] == "disabled"

            # 3. Turned off again and seen as such: "Accesso disattivato" is saved...
            await admin("device_disable", device_id=(await device_named("Prova b4 A"))["id"])
            await page.evaluate("window.dispatchEvent(new Event('online'))")
            await page.wait_for_selector("text=Accesso disattivato")
            await page.goto(base)
            await page.wait_for_selector("text=Accesso disattivato")
            # ...but a link with a new invite, in a newly loaded page, follows the invite.
            await follow_invite(await invite("Prova b4 B"), "Prova b4 B", same_tab=False)

            # 4. A phone that works opens its old (used) link again: it stays as it is.
            used = await invite("Usato")
            other = await browser.new_context(viewport=PHONE, user_agent=ANDROID)
            other_page = await other.new_page()
            await other_page.goto(f"{base}#i={used}")
            await other_page.wait_for_selector("#screen-install:not([hidden])")
            await other.close()
            await page.goto(f"{base}#i={used}")
            await page.wait_for_selector("#days >> text=Recita di Sofia")
            assert (await device_named("Prova b4 B"))["status"] == "active"
        finally:
            await browser.close()


IPHONE_CHROME = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) CriOS/131.0.6778.73 Mobile/15E148 Safari/604.1"
)
# The app opened from the Home Screen icon on iPhone (navigator.standalone is iOS only).
STANDALONE = "Object.defineProperty(navigator, 'standalone', { get: () => true });"


@pytest.mark.parametrize("expected_lingering_tasks", [True])
async def test_iphone_invite_reaches_the_home_screen_app(
    hass: HomeAssistant, hass_client_no_auth: Any, hass_ws_client: Any, socket_enabled: Any
) -> None:
    """iPhone: the browser only explains and keeps the invite in the address it will save (?i=);
    the app opened from the Home Screen (own storage, standalone) uses it, waits, is confirmed
    and shows the calendar. Plan B: the invite link pasted in the app."""
    assert await async_setup_component(hass, "http", {})
    await hass.config.async_set_time_zone("Europe/Rome")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
        options={
            CONF_LANGUAGE: "it",
            OPT_PERSONS: [{"id": "sofia", "name": "Sofia", "color": "#F97316", "role": "child"}],
            OPT_CATEGORIES: [{"id": "scuola", "name": "Scuola", "color": "#10B981"}],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await hass.services.async_call(
        DOMAIN,
        "add_event",
        {
            "category": "scuola",
            "summary": "Recita di Sofia",
            "persons": ["sofia"],
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

    async def invite(name: str) -> tuple[str, str]:
        created = await admin(
            "invite_create",
            invite={"name": name, "persons": ["sofia"], "categories": ["scuola"]},
        )
        link = str(created["link"])
        return link, link.split("#i=", 1)[1]

    async def confirm(name: str) -> None:
        device = next(d for d in (await admin("list"))["devices"] if d["name"] == name)
        assert device["status"] == "pending" and device["label"] == "iPhone · Chrome"
        await admin("device_confirm", device_id=device["id"], accept=True)

    await invite("Zia")  # keeps the web app on
    client = await hass_client_no_auth()
    base = str(client.make_url("/")).rstrip("/") + "/api/family_hub/guest/"

    async with playwright_api.async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
        except Exception as err:  # noqa: BLE001
            pytest.skip(f"Chromium for Playwright is not installed: {err}")
        try:
            # 1. The link in Chrome on iPhone: instructions only, the invite is not used.
            _, token = await invite("Nonna iPhone")
            safari = await browser.new_context(
                viewport=PHONE,
                user_agent=IPHONE_CHROME,
                is_mobile=True,
                has_touch=True,
                locale="it-IT",
                timezone_id="Europe/Rome",
            )
            page = await safari.new_page()
            page.set_default_timeout(TIMEOUT)
            page.on("dialog", lambda dialog: pytest.fail(f"browser dialog: {dialog.message}"))
            await page.goto(f"{base}#i={token}")
            await page.wait_for_selector("#install-ios:not([hidden])")
            steps = await page.inner_text("#install-ios")
            assert "Aggiungi alla schermata Home" in steps and "Apri Family Hub dall'icona" in steps
            assert "Chrome" in steps and "Safari" in steps and "16.4" in steps
            assert not await page.is_visible("#install-continue")
            # The address iOS will save for the icon carries the invite as ?i= (no #).
            assert page.url == f"{base}?i={token}"
            # No manifest on iPhone: its start_url would open the icon without the invite.
            assert await page.evaluate("document.querySelector('link[rel=manifest]')") is None
            assert [
                d for d in (await admin("list"))["devices"] if d["name"] == "Nonna iPhone"
            ] == []
            saved = page.url
            await safari.close()

            # 2. The icon on the Home Screen: its own storage, standalone, the saved address.
            home = await browser.new_context(
                viewport=PHONE,
                user_agent=IPHONE_CHROME,
                is_mobile=True,
                has_touch=True,
                locale="it-IT",
                timezone_id="Europe/Rome",
            )
            await home.add_init_script(STANDALONE)
            app = await home.new_page()
            app.set_default_timeout(TIMEOUT)
            app.on("dialog", lambda dialog: pytest.fail(f"browser dialog: {dialog.message}"))
            await app.goto(saved)
            await app.wait_for_selector("text=In attesa della conferma della famiglia")
            assert "?i=" not in app.url and "#" not in app.url  # taken out at once
            await confirm("Nonna iPhone")
            await app.wait_for_selector("#days >> text=Recita di Sofia")
            assert "token" in await app.evaluate(IDB_KEYS)
            # Opened again from the same icon (the saved address still has the used invite):
            # the phone stays as it is.
            await app.goto(saved)
            await app.wait_for_selector("#days >> text=Recita di Sofia")
            await home.close()

            # 3. Plan B: the icon opened without the invite; the link is pasted.
            link, _ = await invite("Nonno iPhone")
            plain = await browser.new_context(
                viewport=PHONE,
                user_agent=IPHONE_CHROME,
                is_mobile=True,
                has_touch=True,
                locale="it-IT",
                timezone_id="Europe/Rome",
            )
            await plain.add_init_script(STANDALONE)
            await plain.grant_permissions(["clipboard-read", "clipboard-write"], origin=base)
            app = await plain.new_page()
            app.set_default_timeout(TIMEOUT)
            await app.goto(base)
            await app.wait_for_selector("text=Serve un invito")
            # Something that is not an invite: refused, nothing sent.
            await app.fill("#paste-input", "https://example.org/nonèuninvito")
            await app.click("#paste-use")
            await app.wait_for_selector("text=Questo non è un link di invito di Family Hub.")
            # The real link, from the clipboard, at a tap.
            await app.evaluate("link => navigator.clipboard.writeText(link)", link)
            await app.click("text=Incolla il link dell'invito")
            await app.wait_for_selector("text=In attesa della conferma della famiglia")
            await confirm("Nonno iPhone")
            await app.wait_for_selector("#days >> text=Recita di Sofia")
            await plain.close()
        finally:
            await browser.close()


@pytest.mark.parametrize("expected_lingering_tasks", [True])
async def test_my_shifts_in_the_web_app(
    hass: HomeAssistant, hass_client_no_auth: Any, hass_ws_client: Any, socket_enabled: Any
) -> None:
    """A grandmother who still works: her shift types, one day, and a rotation, from her phone;
    Family Hub has them for her guest person."""
    assert await async_setup_component(hass, "http", {})
    await hass.config.async_set_time_zone("Europe/Rome")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
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

    created = await admin(
        "invite_create",
        invite={
            "name": "Nonna Ines",
            "persons": ["sofia"],
            "categories": ["famiglia"],
            "has_shifts": True,
            "shift_color": "#0EA5E9",
        },
    )
    token = created["link"].split("#i=", 1)[1]
    await admin(
        "invite_create", invite={"name": "Zia", "persons": ["sofia"], "categories": ["famiglia"]}
    )
    client = await hass_client_no_auth()
    base = str(client.make_url("/")).rstrip("/") + "/api/family_hub/guest/"

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
            page = await context.new_page()
            page.set_default_timeout(TIMEOUT)
            await page.goto(f"{base}#i={token}")
            await page.click("#install-continue")
            await page.wait_for_selector("text=In attesa della conferma della famiglia")
            device = (await admin("list"))["devices"][0]
            await admin("device_confirm", device_id=device["id"], accept=True)
            await hass.async_block_till_done()
            await page.wait_for_selector("#shifts-button:not([hidden])", timeout=TIMEOUT)
            await page.click("#shifts-button")
            # No types yet: the section is open with the usual three; saved as they are, and the
            # board is there at once (no need to close and open again).
            await page.wait_for_selector("#board-types[open]")
            names = await page.eval_on_selector_all(
                ".shift-type input[type=text]", "els => els.map(e => e.value)"
            )
            assert names == ["Mattina", "Pomeriggio", "Notte"]
            await page.click("#save-types")
            await page.wait_for_selector("[data-tool]:has-text('Mattina')", timeout=TIMEOUT)
            labels = await page.eval_on_selector_all(
                ".board-tool", "els => els.map(e => e.textContent.trim())"
            )
            assert labels == ["MAMattina", "POPomeriggio", "NONotte", "Riposo", "Cancella"]
            assert not await page.locator("#board-types").evaluate("d => d.open")
            # Three days of the month shown (the next month if this one ends too soon).
            start = dt_util.now().date() + timedelta(days=1)
            if (start + timedelta(days=2)).month != start.month:
                await page.click(".board-nav button:has-text('›')")
                start = (start + timedelta(days=3)).replace(day=1)
            days = [(start + timedelta(days=n)).isoformat() for n in range(3)]
            await page.click("[data-tool]:has-text('Mattina')")
            for day in days:
                await page.click(f"[data-day='{day}']")
            assert "has-shift" in await page.get_attribute(f"[data-day='{days[0]}']", "class")
            # A second tap on the same day takes it away.
            await page.click(f"[data-day='{days[2]}']")
            assert "has-shift" not in await page.get_attribute(f"[data-day='{days[2]}']", "class")
            assert "2" in await page.inner_text("#board-save")
            await page.click("#board-save")
            await page.wait_for_selector("text=Turni salvati.")
            # A rotation: Notte, Riposo for one week, from ten days on.
            rotation_start = (dt_util.now().date() + timedelta(days=10)).isoformat()
            await page.click("[data-pattern]:has-text('Notte')")
            await page.click("[data-pattern='']")
            await page.fill("#rotation-start", rotation_start)
            await page.select_option("#rotation-weeks", "1")
            await page.click("#apply-rotation")
            await page.wait_for_selector("text=Turni salvati.")
            assert await page.evaluate("document.documentElement.scrollWidth") <= PHONE["width"]
        finally:
            await browser.close()
    await hass.async_block_till_done()
    person_id = entry.runtime_data.guests.devices[device["id"]]["person_id"]
    shifts = sorted(
        (r["start"][:10], r["summary"])
        for r in entry.runtime_data.store.events.values()
        if person_id in r["persons"]
    )
    mornings = [d for d, summary in shifts if summary == "Nonna Ines · Mattina"]
    assert mornings == days[:2]
    first = dt_util.now().date() + timedelta(days=10)
    nights = [d for d, summary in shifts if summary == "Nonna Ines · Notte"]
    assert nights == [(first + timedelta(days=n)).isoformat() for n in (0, 2, 4, 6)]
    # In Family Hub's own calendar, with the name in front.
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": "calendar.family_hub_famiglia",
            "start_date_time": f"{days[0]} 00:00:00",
            "end_date_time": f"{days[1]} 23:59:00",
        },
        blocking=True,
        return_response=True,
    )
    summaries = [e["summary"] for e in response["calendar.family_hub_famiglia"]["events"]]
    assert summaries.count("Nonna Ines · Mattina") == 2
    person = next(p for p in entry.options["persons"] if p["id"] == person_id)
    assert person["color"] == "#0EA5E9" and person["name"] == "Nonna Ines"
