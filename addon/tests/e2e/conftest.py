"""Runs the add-on server and a fake Home Assistant in background threads, and a tablet browser.

The browser is Microsoft Edge when it is installed (Playwright channel "msedge"), so no
browser download is needed on a machine that has Edge. Set FH_E2E_CHANNEL to change it,
or FH_E2E_CHANNEL=chromium to use Playwright's own Chromium.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
from aiohttp import web
from app.ha_link import HAClient
from app.server import create_app
from playwright.sync_api import Browser, Page, sync_playwright

from tests.fake_ha import ADMIN_USER, TOKEN, FakeHA
from tests.helpers import ADULT_USER, TEST_PEERS

# The browser cannot send the Ingress header on its WebSocket, so the test-only cookie stands in.
os.environ["FH_TEST_COOKIE"] = "1"

TABLET = {"width": 1024, "height": 768}


class Stack:
    """Fake Home Assistant + add-on server, running on their own event loop."""

    def __init__(self, calendars: bool) -> None:
        self.fake = FakeHA(calendars=calendars)
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.url = ""
        self.ha: HAClient | None = None
        self._runners: list[web.AppRunner] = []

    def run(self, coro: Any, timeout: float = 10) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout)

    async def _boot(self) -> None:
        fake_runner = web.AppRunner(self.fake.app, shutdown_timeout=0.5)
        await fake_runner.setup()
        await web.TCPSite(fake_runner, "127.0.0.1", 0).start()
        self._runners.append(fake_runner)
        fake_port = fake_runner.addresses[0][1]

        self.ha = HAClient(f"http://127.0.0.1:{fake_port}/api/websocket", TOKEN)
        hub_runner = web.AppRunner(create_app(self.ha, TEST_PEERS), shutdown_timeout=0.5)
        await hub_runner.setup()
        await web.TCPSite(hub_runner, "127.0.0.1", 0).start()
        self._runners.append(hub_runner)
        self.url = f"http://127.0.0.1:{hub_runner.addresses[0][1]}"

    async def _stop(self) -> None:
        for runner in self._runners:
            await runner.cleanup()

    def start(self) -> None:
        self.thread.start()
        self.run(self._boot())
        for _ in range(200):
            if self.ha is not None and self.ha.connected:
                break
            time.sleep(0.02)
        assert self.ha is not None and self.ha.connected, "add-on could not reach fake HA"

    def stop(self) -> None:
        self.run(self._stop(), timeout=20)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)


@pytest.fixture(scope="module")
def stack_full() -> Iterator[Stack]:
    stack = Stack(calendars=True)
    stack.start()
    yield stack
    stack.stop()


@pytest.fixture(scope="module")
def stack_empty() -> Iterator[Stack]:
    stack = Stack(calendars=False)
    stack.start()
    yield stack
    stack.stop()


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    channel = os.environ.get("FH_E2E_CHANNEL", "msedge")
    with sync_playwright() as p:
        if channel == "chromium":
            browser = p.chromium.launch(headless=True)
        else:
            browser = p.chromium.launch(channel=channel, headless=True)
        yield browser
        browser.close()


@pytest.fixture
def tablet(browser: Browser) -> Iterator[Page]:
    """A new tablet-sized page with touch enabled, signed in as an adult."""
    with tablet_as(browser, ADULT_USER) as page:
        yield page


@pytest.fixture
def admin_tablet(browser: Browser) -> Iterator[Page]:
    """A tablet page signed in as a Home Assistant administrator (for a new install)."""
    with tablet_as(browser, ADMIN_USER) as page:
        yield page


@contextlib.contextmanager
def tablet_as(browser: Browser, user: str | None) -> Iterator[Page]:
    """A tablet page whose requests carry the Ingress user header (or none)."""
    context = browser.new_context(viewport=TABLET, has_touch=True, is_mobile=False)
    if user is not None:
        context.set_extra_http_headers({"X-Remote-User-Id": user})
    page = context.new_page()
    try:
        yield page
    finally:
        context.close()
