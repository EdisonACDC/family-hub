"""Helpers shared by the add-on tests: a running fake Home Assistant plus the add-on server."""

from __future__ import annotations

import asyncio
from typing import Any

from aiohttp.test_utils import TestClient, TestServer
from app.ha_link import HAClient
from app.server import create_app

from tests.fake_ha import TOKEN, FakeHA

ADULT_USER = "u-mamma"
CHILD_USER = "u-sofia"
GUEST_USER = "u-guest"
TEST_PEERS = frozenset({"127.0.0.1"})


async def started(fake: FakeHA, token: str = TOKEN) -> tuple[TestServer, TestClient, HAClient]:
    ha_server = TestServer(fake.app)
    await ha_server.start_server()
    url = str(ha_server.make_url("/api/websocket"))
    ha = HAClient(url, token)
    client = TestClient(TestServer(create_app(ha, TEST_PEERS)))
    await client.start_server()
    for _ in range(100):
        if ha.connected and fake._subs:
            break
        await asyncio.sleep(0.05)
    return ha_server, client, ha


async def shutdown(ha_server: TestServer, client: TestClient) -> None:
    await client.close()
    await ha_server.close()


async def connect(client: TestClient, user: str | None) -> Any:
    headers = {"X-Remote-User-Id": user} if user else {}
    ws = await client.ws_connect("/ws", headers=headers)
    # The server first says who the user is, whether Home Assistant is connected, and the theme.
    for _ in range(3):
        await ws.receive_json(timeout=5)
    return ws


async def request(ws: Any, payload: dict[str, Any]) -> dict[str, Any]:
    await ws.send_json(payload)
    while True:
        msg = await ws.receive_json(timeout=5)
        if msg.get("type") == "result" and msg.get("id") == payload["id"]:
            return msg
