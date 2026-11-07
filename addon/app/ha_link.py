"""Minimal Home Assistant WebSocket client used by the add-on.

The add-on keeps no state of its own: every read and every write goes through this
connection. Subscriptions are owned by the caller and must be created again after a
reconnect. The token is never logged.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import aiohttp

LOGGER = logging.getLogger(__name__)

StreamHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]
StateHandler = Callable[[bool], Coroutine[Any, Any, None]]

RECONNECT_MIN = 1.0
RECONNECT_MAX = 30.0


class HAError(Exception):
    """Home Assistant refused a command or the connection failed. ``code`` is HA's error code."""

    def __init__(self, message: str, code: str = "ha_error") -> None:
        super().__init__(message)
        self.code = code


class HAClient:
    """One authenticated WebSocket to Home Assistant, reconnected in the background."""

    def __init__(self, url: str, token: str) -> None:
        self._url = url
        self._token = token
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._streams: dict[int, StreamHandler] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._write_lock = asyncio.Lock()
        self._announce_task: asyncio.Task[None] | None = None
        self.on_connection: StateHandler | None = None
        self.connected = False

    async def run(self) -> None:
        """Keep the connection alive until cancelled."""
        self._session = aiohttp.ClientSession()
        delay = RECONNECT_MIN
        try:
            while True:
                try:
                    await self._connect_and_read()
                    delay = RECONNECT_MIN
                except asyncio.CancelledError:
                    raise
                except (aiohttp.ClientError, HAError, OSError) as err:
                    LOGGER.warning("Home Assistant connection failed: %s", err)
                finally:
                    await self._mark_disconnected()
                await asyncio.sleep(delay)
                delay = min(delay * 2, RECONNECT_MAX)
        finally:
            await self._session.close()

    async def _connect_and_read(self) -> None:
        assert self._session is not None
        ws = await self._session.ws_connect(self._url, heartbeat=30)
        self._ws = ws
        try:
            first = await ws.receive_json()
            if first.get("type") != "auth_required":
                raise HAError("unexpected greeting from Home Assistant")
            await ws.send_json({"type": "auth", "access_token": self._token})
            answer = await ws.receive_json()
            if answer.get("type") != "auth_ok":
                raise HAError("Home Assistant rejected the add-on token")
            self.connected = True
            # Announce in a task: the handler sends commands whose replies are read below.
            self._announce_task = asyncio.create_task(self._announce(True))
            async for raw in ws:
                if raw.type != aiohttp.WSMsgType.TEXT:
                    break
                await self._dispatch(raw.json())
        finally:
            self._ws = None

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        if msg.get("type") == "result":
            future = self._pending.pop(msg["id"], None)
            if future is not None and not future.done():
                future.set_result(msg)
        elif msg.get("type") == "event":
            handler = self._streams.get(msg["id"])
            if handler is not None:
                # Run in a task: handlers may send commands whose replies this loop must read.
                task: asyncio.Task[None] = asyncio.create_task(handler(msg["event"]))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

    async def _mark_disconnected(self) -> None:
        was_connected = self.connected
        self.connected = False
        for future in self._pending.values():
            if not future.done():
                future.set_exception(HAError("connection lost"))
        self._pending.clear()
        self._streams.clear()  # subscriptions die with the connection
        if was_connected:
            await self._announce(False)

    async def _announce(self, connected: bool) -> None:
        """Tell the owner about a connection change. Failures are logged, not raised."""
        if self.on_connection is None:
            return
        try:
            await self.on_connection(connected)
        except HAError as err:
            LOGGER.warning("Could not set up Home Assistant subscriptions: %s", err)

    async def _send(
        self, msg_type: str, payload: dict[str, Any], stream: StreamHandler | None = None
    ) -> tuple[int, dict[str, Any]]:
        if not self.connected or self._ws is None:
            raise HAError("not connected to Home Assistant")
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        async with self._write_lock:
            msg_id = self._next_id
            self._next_id += 1
            self._pending[msg_id] = future
            # Register the stream before sending: events may arrive right after the result.
            if stream is not None:
                self._streams[msg_id] = stream
            await self._ws.send_json({"id": msg_id, "type": msg_type, **payload})
        try:
            reply = await asyncio.wait_for(future, timeout=15)
        except BaseException:
            self._streams.pop(msg_id, None)
            raise
        if not reply.get("success"):
            self._streams.pop(msg_id, None)
            error = reply.get("error", {})
            raise HAError(error.get("message", "unknown error"), error.get("code", "ha_error"))
        return msg_id, reply

    async def call(self, msg_type: str, **payload: Any) -> Any:
        """Send one command and return its result. Raises HAError on failure."""
        _, reply = await self._send(msg_type, payload)
        return reply.get("result")

    async def subscribe(self, msg_type: str, handler: StreamHandler, **payload: Any) -> int:
        """Start a subscription. ``handler`` gets every event; returns the subscription id."""
        msg_id, _ = await self._send(msg_type, payload, stream=handler)
        return msg_id

    async def unsubscribe(self, subscription_id: int) -> None:
        """Stop a subscription made with :meth:`subscribe`. Missing ones are ignored."""
        self._streams.pop(subscription_id, None)
        if self.connected:
            with contextlib.suppress(HAError):
                await self.call("unsubscribe_events", subscription=subscription_id)
