"""The setup guide: only adults read and save, the add-on relays to family_hub/config/*,
and the test-only cookie stays off unless FH_TEST_COOKIE=1."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer
from app.ha_link import HAClient
from app.server import create_app

from tests.fake_ha import ADMIN_USER, FakeHA, default_config
from tests.helpers import ADULT_USER, CHILD_USER, GUEST_USER, connect, request, shutdown, started


def _run(scenario: Any) -> None:
    asyncio.run(scenario())


def _config() -> dict[str, Any]:
    config = default_config(configured=False)
    config.pop("configured")
    config["family"]["family_name"] = "Famiglia Esempio"
    config["persons"] = [
        {"name": "Mamma", "color": "#2563EB", "role": "adult", "ha_user_id": "u-mamma"}
    ]
    config["categories"].append({"id": "sport", "name": "Sport", "color": "#F59E0B"})
    return config


def test_adult_reads_the_configuration() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, ADULT_USER)
            reply = await request(ws, {"id": 1, "op": "config_get"})
            assert reply["ok"] is True
            assert reply["result"]["configured"] is True
            assert reply["result"]["family"]["family_name"] == "Esempio"
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_adult_saves_and_the_calendars_follow() -> None:
    async def scenario() -> None:
        fake = FakeHA(calendars=False)
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, ADMIN_USER)
            reply = await request(ws, {"id": 2, "op": "config_save", "config": _config()})
            assert reply == {"id": 2, "type": "result", "ok": True}
            (saved,) = fake.saved_configs
            assert saved["family"]["family_name"] == "Famiglia Esempio"
            assert saved["configured"] is True
            # The add-on subscribes to the new calendars shortly after saving.
            for _ in range(60):
                if any(e.startswith("calendar.family_hub_sport") for e in fake.events):
                    break
                await asyncio.sleep(0.05)
            assert "calendar.family_hub_sport" in fake.events
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_home_assistant_error_reaches_the_guide() -> None:
    async def scenario() -> None:
        fake = FakeHA(calendars=False)
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, ADMIN_USER)
            config = _config()
            config["family"]["family_name"] = ""
            reply = await request(ws, {"id": 3, "op": "config_save", "config": config})
            assert reply["ok"] is False
            assert reply["error"] == "invalid_config"
            assert "family_name" in reply["detail"]
            assert fake.saved_configs == []
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


@pytest.mark.parametrize("user", [CHILD_USER, GUEST_USER, None])
def test_only_adults_read_or_save_the_configuration(user: str | None) -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, user)
            read = await request(ws, {"id": 1, "op": "config_get"})
            save = await request(ws, {"id": 2, "op": "config_save", "config": _config()})
            assert read == {"id": 1, "type": "result", "ok": False, "error": "forbidden"}
            assert save == {"id": 2, "type": "result", "ok": False, "error": "forbidden"}
            assert fake.saved_configs == []
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_new_install_lets_only_administrators_run_the_guide() -> None:
    """With no adult linked to a Home Assistant user, administrators run the family."""

    async def scenario() -> None:
        fake = FakeHA(calendars=False)
        ha_server, client, _ = await started(fake)
        try:
            admin = await connect(client, ADMIN_USER)
            assert (await request(admin, {"id": 1, "op": "config_get"}))["ok"] is True
            await admin.close()
            member = await connect(client, ADULT_USER)
            assert (await request(member, {"id": 2, "op": "config_get"}))["ok"] is False
            await member.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_after_an_adult_is_linked_the_normal_rules_apply() -> None:
    async def scenario() -> None:
        fake = FakeHA(calendars=False)
        ha_server, client, _ = await started(fake)
        try:
            admin = await connect(client, ADMIN_USER)
            assert (await request(admin, {"id": 1, "op": "config_save", "config": _config()}))["ok"]
            await admin.close()
            # The saved configuration links Mamma (adult) to u-mamma. An administrator of Home
            # Assistant who is no person is still an adult: the family's tablet is never a guest.
            admin = await connect(client, ADMIN_USER)
            assert (await request(admin, {"id": 2, "op": "config_get"}))["ok"] is True
            await admin.close()
            mamma = await connect(client, ADULT_USER)
            assert (await request(mamma, {"id": 3, "op": "config_get"}))["ok"] is True
            await mamma.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_cookie_is_ignored_unless_test_mode_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            cookie = {"Cookie": f"fh_user={ADULT_USER}"}
            monkeypatch.delenv("FH_TEST_COOKIE", raising=False)
            ws = await client.ws_connect("/ws", headers=cookie)
            assert (await ws.receive_json(timeout=5))["role"] == "guest"
            await ws.close()

            monkeypatch.setenv("FH_TEST_COOKIE", "1")
            ws = await client.ws_connect("/ws", headers=cookie)
            assert (await ws.receive_json(timeout=5))["role"] == "adult"
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_header_wins_over_cookie_in_test_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            monkeypatch.setenv("FH_TEST_COOKIE", "1")
            ws = await client.ws_connect(
                "/ws", headers={"Cookie": f"fh_user={ADULT_USER}", "X-Remote-User-Id": CHILD_USER}
            )
            assert (await ws.receive_json(timeout=5))["role"] == "child"
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_outside_clients_stay_blocked_with_test_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server = TestServer(fake.app)
        await ha_server.start_server()
        ha = HAClient(str(ha_server.make_url("/api/websocket")), "test-token")
        client = TestClient(TestServer(create_app(ha, frozenset({"10.9.9.9"}))))
        await client.start_server()
        try:
            monkeypatch.setenv("FH_TEST_COOKIE", "1")
            response = await client.get("/", headers={"X-Remote-User-Id": ADULT_USER})
            assert response.status == 403
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_theme_is_sent_on_connect_and_after_a_save() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        fake.config["screen"]["theme"] = "dark"
        ha_server, client, _ = await started(fake)
        try:
            ws = await client.ws_connect("/ws", headers={"X-Remote-User-Id": ADULT_USER})
            themes = [(await ws.receive_json(timeout=5)) for _ in range(3)]
            assert {
                "type": "theme",
                "theme": "dark",
                "language": "it",
                "time_format": "24h",
                "first_weekday": "monday",
                "week_from_today": True,
            } in themes
            config = _config()
            config["screen"] = {"theme": "light"}
            await ws.send_json({"id": 1, "op": "config_save", "config": config})
            seen = []
            for _ in range(2):  # the theme broadcast and the reply
                seen.append(await ws.receive_json(timeout=5))
            assert {
                "type": "theme",
                "theme": "light",
                "language": "it",
                "time_format": "24h",
                "first_weekday": "monday",
                "week_from_today": True,
            } in seen
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)
