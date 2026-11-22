"""0.10.0b2: "Completa" in the guests' web app is the add-on's panel itself. Its copies must be
the panel's files unchanged (run scripts/sync_guest_panel.py after changing the panel), the
page loads the bridge before the panel, and the web app serves them with its strict headers.
Nothing for Condivisione, the guide or settings is reachable through the bridge."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.family_hub.const import (
    CONF_FAMILY_NAME,
    CONF_LANGUAGE,
    DOMAIN,
    OPT_CATEGORIES,
    OPT_PERSONS,
)
from custom_components.family_hub.guest_http import CSP, FILES

ROOT = Path(__file__).resolve().parent.parent
WWW = ROOT / "custom_components" / "family_hub" / "guest_www"


def _sync() -> Any:
    spec = importlib.util.spec_from_file_location("sync", ROOT / "scripts/sync_guest_panel.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _text(data: bytes) -> str:
    # Git may check the files out with Windows line endings: the same content either way.
    return data.decode("utf-8").replace("\r\n", "\n")


def test_copies_are_the_panel_unchanged() -> None:
    for name, data in _sync().expected().items():
        assert _text((WWW / name).read_bytes()) == _text(data), (
            f"{name} differs from the panel: run python scripts/sync_guest_panel.py"
        )


def test_page_loads_the_bridge_before_the_panel() -> None:
    page = _text((WWW / "full.html").read_bytes())
    scripts = re.findall(r'<script src="([^"]+)"', page)
    names = [s.split("/")[-1].split("?")[0] for s in scripts]
    assert names == ["panel-i18n.js", "panel-mdi.js", "bridge.js", "panel-app.js"]
    assert "<script>" not in page and "style=" not in page
    version = json.loads((WWW.parent / "manifest.json").read_text("utf-8"))["version"]
    assert f'content="{version}"' in page


def test_every_file_of_the_page_is_served() -> None:
    page = _text((WWW / "full.html").read_bytes())
    for ref in re.findall(r'(?:src|href)="/api/family_hub/guest/([^"?]+)', page):
        assert ref in FILES, ref
        assert (WWW / ref).is_file(), ref


def test_bridge_never_relays_admin_requests() -> None:
    """The bridge answers a fixed list of the panel's requests; everything else is refused."""
    bridge = _text((WWW / "bridge.js").read_bytes())
    cases = set(re.findall(r'case "([a-z_]+)"', bridge))
    assert cases == {
        "status",
        "calendars",
        "events",
        "weather",
        "service",
        "todo_lists",
        "todo_items",
        "todo_add",
        "todo_update",
        "shifts",
        "shifts_save",
        "shifts_apply",
        "chosen_dates",
    }
    # Only the guests' API, never Home Assistant's own.
    assert re.findall(r'"/api/[^"]*"', bridge) == ['"/api/family_hub/guest/"']
    assert "WebSocket(" not in bridge and "access_token" not in bridge.lower()


@pytest.mark.parametrize("name", ["full.html", "bridge.js", "panel-app.js", "panel.css"])
async def test_served_with_strict_headers(
    hass: HomeAssistant, hass_client_no_auth: Any, hass_ws_client: Any, name: str
) -> None:
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it"},
        options={
            OPT_PERSONS: [{"id": "sofia", "name": "Sofia", "color": "#F97316", "role": "child"}],
            OPT_CATEGORIES: [{"id": "famiglia", "name": "Famiglia", "color": "#10B981"}],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    ws = await hass_ws_client()
    await ws.send_json_auto_id(
        {
            "type": "family_hub/guest/invite_create",
            "invite": {"name": "Prova", "persons": ["sofia"], "categories": ["famiglia"]},
        }
    )
    assert (await ws.receive_json())["success"]
    client = await hass_client_no_auth()
    answer = await client.get(f"/api/family_hub/guest/{name}")
    assert answer.status == 200
    assert answer.headers["Content-Security-Policy"] == CSP
    assert "Access-Control-Allow-Origin" not in answer.headers
    assert answer.headers["Content-Type"] == FILES[name]
