"""The guest web app (PWA) and its small API, under /api/family_hub/guest/.

Served by the integration and not by the add-on, because Ingress needs a Home Assistant login.
The views do not use Home Assistant's login (requires_auth=False): a phone proves itself with
its own device token, sent in the Authorization header (never in a URL). The invite token only
travels in the link's fragment and in the body of the activation request.

Every answer carries strict security headers and no CORS headers. While no family has an open
invite or a device, every address here answers 404.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from http import HTTPStatus
from pathlib import Path
from typing import Any

from aiohttp import web
from homeassistant.core import HomeAssistant
from homeassistant.helpers.http import HomeAssistantView

from .guests import GuestError, GuestHub, GuestManager, guest_hub

LOGGER = logging.getLogger(__name__)

# An invite in the address (?i=..., used by the iPhone's Home Screen icon) must never reach a log.
_INVITE_IN_URL = re.compile(r"([?&#]i=)[A-Za-z0-9_-]+")


class _HideInvite(logging.Filter):
    """For aiohttp's access log (off in Home Assistant unless raised to INFO): the invite code in
    a guest address is replaced by ***, whatever the log level."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "family_hub/guest" in message and "i=" in message:
            record.msg = _INVITE_IN_URL.sub(r"\1***", message)
            record.args = ()
        return True


HIDE_INVITE = _HideInvite()

WWW = Path(__file__).parent / "guest_www"
BASE = "/api/family_hub/guest"
MAX_BODY = 8192
MAX_TOKEN = 128
FILES: dict[str, str] = {
    "app.js": "text/javascript; charset=utf-8",
    "app.css": "text/css; charset=utf-8",
    "sw.js": "text/javascript; charset=utf-8",
    "manifest.json": "application/manifest+json; charset=utf-8",
    "icon-192.png": "image/png",
    "icon-512.png": "image/png",
    "icon-maskable-512.png": "image/png",
    "apple-touch-icon.png": "image/png",
    # "Completa" (0.10.0b2): the panel's own page, script and style, copied unchanged from the
    # add-on by scripts/sync_guest_panel.py, and the bridge to this API.
    "full.html": "text/html; charset=utf-8",
    "bridge.js": "text/javascript; charset=utf-8",
    "full.css": "text/css; charset=utf-8",
    "panel-app.js": "text/javascript; charset=utf-8",
    "panel-i18n.js": "text/javascript; charset=utf-8",
    "panel-mdi.js": "text/javascript; charset=utf-8",
    "panel.css": "text/css; charset=utf-8",
}
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; manifest-src 'self'; worker-src 'self'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'; object-src 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def _headers(cache: str = "no-store") -> dict[str, str]:
    return {**SECURITY_HEADERS, "Cache-Control": cache}


def _json(data: Any, status: int = 200) -> web.Response:
    return web.Response(
        text=json.dumps(data, ensure_ascii=False),
        status=status,
        content_type="application/json",
        charset="utf-8",
        headers=_headers(),
    )


def _fail(err: GuestError) -> web.Response:
    """Only the short code; never a detail of Home Assistant."""
    return _json({"error": err.code}, err.status)


def _not_found() -> web.Response:
    return web.Response(status=404, headers=_headers())


def _address(request: web.Request) -> str:
    return str(request.remote or "?")


async def _body(request: web.Request) -> Any:
    if request.content_type != "application/json":
        raise GuestError("invalid", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
    if request.content_length is not None and request.content_length > MAX_BODY:
        raise GuestError("too_large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
    raw = await request.content.read(MAX_BODY + 1)
    if len(raw) > MAX_BODY:
        raise GuestError("too_large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as err:
        raise GuestError("invalid", 422) from err


def _bearer(request: web.Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token or len(token) > MAX_TOKEN:
        raise GuestError("unknown", 401)
    return token


class _GuestView(HomeAssistantView):
    requires_auth = False
    cors_allowed = False

    def _hub(self, request: web.Request) -> GuestHub | None:
        hass: HomeAssistant = request.app["hass"]
        hub = guest_hub(hass)
        return hub if hub.enabled() else None

    def _limit(self, hub: GuestHub, request: web.Request, write: bool, device: str = "") -> None:
        """One hit for the address, or (with ``device``) one for the device."""
        limiter = hub.write_limit if write else hub.read_limit
        key = f"dev:{device}" if device else f"ip:{_address(request)}"
        if not limiter.allow(key):
            raise GuestError("slow_down", HTTPStatus.TOO_MANY_REQUESTS)

    def _device(
        self, hub: GuestHub, request: web.Request, write: bool = False
    ) -> tuple[GuestManager, dict[str, Any]]:
        self._limit(hub, request, write)
        found = hub.device_for(_bearer(request))
        if found is None:
            raise GuestError("unknown", 401)
        manager, device = found
        self._limit(hub, request, write, device["id"])
        manager.touch(device)
        return manager, device


class GuestPageView(_GuestView):
    """The web app's page. The invite comes in the fragment (#i=, never sent to the server) or,
    when the iPhone's Home Screen icon opens the app, in ?i=: the page alone reads it, takes it
    out of the address at once, and this answer is never stored."""

    url = f"{BASE}/"
    name = "api:family_hub:guest"

    async def get(self, request: web.Request) -> web.StreamResponse:
        if self._hub(request) is None:
            return _not_found()
        text = await request.app["hass"].async_add_executor_job(
            (WWW / "index.html").read_text, "utf-8"
        )
        cache = "no-store" if request.query_string else "no-cache"
        return web.Response(
            text=text, content_type="text/html", charset="utf-8", headers=_headers(cache)
        )


class GuestFileView(_GuestView):
    """The app's own files, from a fixed list."""

    url = BASE + "/{name}"
    name = "api:family_hub:guest:file"

    async def get(self, request: web.Request, name: str) -> web.StreamResponse:
        if self._hub(request) is None or name not in FILES:
            return _not_found()
        data = await request.app["hass"].async_add_executor_job((WWW / name).read_bytes)
        headers = _headers("no-cache")
        if name == "sw.js":
            headers["Service-Worker-Allowed"] = f"{BASE}/"
        return web.Response(body=data, headers={**headers, "Content-Type": FILES[name]})


class GuestActivateView(_GuestView):
    """POST {"token": invite token}: the phone becomes a device waiting for an adult."""

    url = f"{BASE}/api/activate"
    name = "api:family_hub:guest:activate"

    async def post(self, request: web.Request) -> web.Response:
        hub = self._hub(request)
        if hub is None:
            return _not_found()
        address = _address(request)
        try:
            if hub.activation.blocked(address):
                raise GuestError("slow_down", HTTPStatus.TOO_MANY_REQUESTS)
            self._limit(hub, request, write=True)
            body = await _body(request)
            token = body.get("token") if isinstance(body, dict) else None
            if not isinstance(token, str) or not 20 <= len(token) <= MAX_TOKEN:
                hub.activation.failed(address)
                raise GuestError("invite_invalid", 403)
            found = hub.invite_for(token)
            if found is None:
                hub.activation.failed(address)
                raise GuestError("invite_invalid", 403)
            manager, invite = found
            try:
                device_token = await manager.async_activate(
                    invite, request.headers.get("User-Agent", "")
                )
            except GuestError:
                hub.activation.failed(address)
                raise
        except GuestError as err:
            return _fail(err)
        return _json({"token": device_token, "status": "pending"})


class GuestMeView(_GuestView):
    """Who the phone is, what it may do and see. A due token rotation is answered here."""

    url = f"{BASE}/api/me"
    name = "api:family_hub:guest:me"

    async def get(self, request: web.Request) -> web.Response:
        hub = self._hub(request)
        if hub is None:
            return _not_found()
        try:
            manager, device = self._device(hub, request)
            if device["status"] in ("rejected", "disabled"):
                raise GuestError(str(device["status"]), 403)
            result = manager.me(device)
            if device["status"] == "active":
                new = await manager.async_rotate_if_due(device)
                if new is not None:
                    result["token"] = new
        except GuestError as err:
            return _fail(err)
        return _json(result)


class GuestEventsView(_GuestView):
    """GET ?from=YYYY-MM-DD&days=N lists; POST adds an appointment."""

    url = f"{BASE}/api/events"
    name = "api:family_hub:guest:events"

    async def get(self, request: web.Request) -> web.Response:
        hub = self._hub(request)
        if hub is None:
            return _not_found()
        try:
            manager, device = self._device(hub, request)
            manager.check_active(device)
            if set(request.query) - {"from", "days"}:
                raise GuestError("invalid", 422)
            try:
                start = date.fromisoformat(request.query.get("from", ""))
                days = int(request.query.get("days", "14"))
            except ValueError as err:
                raise GuestError("invalid", 422) from err
            items = manager.list_events(device, start, days)
            # External calendars (school, Google, ICS): only those allowed to this phone.
            items += await manager.async_external_events(device, start, days)
            items.sort(
                key=lambda item: (str(item["start"])[:10], str(item["start"]), item["title"])
            )
        except GuestError as err:
            return _fail(err)
        return _json({"events": items})

    async def post(self, request: web.Request) -> web.Response:
        hub = self._hub(request)
        if hub is None:
            return _not_found()
        try:
            manager, device = self._device(hub, request, write=True)
            manager.check_active(device)
            item = await manager.async_guest_add(device, await _body(request))
        except GuestError as err:
            return _fail(err)
        return _json({"event": item}, 201)


class GuestEventView(_GuestView):
    """PUT changes, DELETE removes one of the phone's own appointments."""

    url = BASE + "/api/events/{item_id}"
    name = "api:family_hub:guest:event"

    async def put(self, request: web.Request, item_id: str) -> web.Response:
        hub = self._hub(request)
        if hub is None:
            return _not_found()
        try:
            manager, device = self._device(hub, request, write=True)
            manager.check_active(device)
            item = await manager.async_guest_update(device, item_id, await _body(request))
        except GuestError as err:
            return _fail(err)
        return _json({"event": item})

    async def delete(self, request: web.Request, item_id: str) -> web.Response:
        hub = self._hub(request)
        if hub is None:
            return _not_found()
        try:
            manager, device = self._device(hub, request, write=True)
            await manager.async_guest_delete(device, item_id)
        except GuestError as err:
            return _fail(err)
        return _json({"deleted": True})


class GuestPushView(_GuestView):
    """POST {"subscription": {...}} turns notifications on; DELETE turns them off."""

    url = f"{BASE}/api/push"
    name = "api:family_hub:guest:push"

    async def post(self, request: web.Request) -> web.Response:
        hub = self._hub(request)
        if hub is None:
            return _not_found()
        try:
            manager, device = self._device(hub, request, write=True)
            body = await _body(request)
            if isinstance(body, dict) and isinstance(body.get("blocked"), bool):
                # The phone's settings block notifications (or no longer do): the adults see it.
                await manager.async_set_blocked(device, body["blocked"])
                return _json({"push": False, "blocked": body["blocked"]})
            subscription = body.get("subscription") if isinstance(body, dict) else None
            if subscription is None:
                raise GuestError("invalid", 422)
            on = await manager.async_set_push(device, subscription)
        except GuestError as err:
            return _fail(err)
        return _json({"push": on})

    async def delete(self, request: web.Request) -> web.Response:
        hub = self._hub(request)
        if hub is None:
            return _not_found()
        try:
            manager, device = self._device(hub, request, write=True)
            on = await manager.async_set_push(device, None)
        except GuestError as err:
            return _fail(err)
        return _json({"push": on})


class GuestShiftsView(_GuestView):
    """GET ?from=YYYY-MM-DD&days=N: the guest's own shift types and shifts."""

    url = f"{BASE}/api/shifts"
    name = "api:family_hub:guest:shifts"

    async def get(self, request: web.Request) -> web.Response:
        hub = self._hub(request)
        if hub is None:
            return _not_found()
        try:
            manager, device = self._device(hub, request)
            if set(request.query) - {"from", "days"}:
                raise GuestError("invalid", 422)
            try:
                start = date.fromisoformat(request.query.get("from", ""))
                days = int(request.query.get("days", "28"))
            except ValueError as err:
                raise GuestError("invalid", 422) from err
            result = manager.shift_state(device, start, days)
        except GuestError as err:
            return _fail(err)
        return _json(result)


class GuestShiftActionView(_GuestView):
    """PUT types (the guest's shift types); POST apply (chosen days) or rotation (repeating)."""

    url = BASE + "/api/shifts/{action}"
    name = "api:family_hub:guest:shifts:action"

    async def put(self, request: web.Request, action: str) -> web.Response:
        hub = self._hub(request)
        if hub is None or action != "types":
            return _not_found()
        try:
            manager, device = self._device(hub, request, write=True)
            await manager.async_save_shift_types(device, await _body(request))
        except GuestError as err:
            return _fail(err)
        return _json({"saved": True})

    async def post(self, request: web.Request, action: str) -> web.Response:
        hub = self._hub(request)
        if hub is None or action not in ("apply", "rotation"):
            return _not_found()
        try:
            manager, device = self._device(hub, request, write=True)
            written = await manager.async_apply_shifts(
                device, await _body(request), rotation=action == "rotation"
            )
        except GuestError as err:
            return _fail(err)
        return _json({"written": written})


class GuestListView(_GuestView):
    """One of the to-do lists an adult gave this phone: GET the items; POST {"add": text} or
    {"item": id, "done": bool} when it may change them. Anything else is 403."""

    url = BASE + "/api/lists/{list_id}"
    name = "api:family_hub:guest:list"

    async def get(self, request: web.Request, list_id: str) -> web.Response:
        hub = self._hub(request)
        if hub is None:
            return _not_found()
        try:
            manager, device = self._device(hub, request)
            items = await manager.async_list_items(device, list_id)
        except GuestError as err:
            return _fail(err)
        return _json({"items": items})

    async def post(self, request: web.Request, list_id: str) -> web.Response:
        hub = self._hub(request)
        if hub is None:
            return _not_found()
        try:
            manager, device = self._device(hub, request, write=True)
            await manager.async_list_change(device, list_id, await _body(request))
            items = await manager.async_list_items(device, list_id)
        except GuestError as err:
            return _fail(err)
        return _json({"items": items})


class GuestWasteView(_GuestView):
    """GET ?from=YYYY-MM-DD&days=N: the rubbish pickups, when the adult turned them on."""

    url = f"{BASE}/api/waste"
    name = "api:family_hub:guest:waste"

    async def get(self, request: web.Request) -> web.Response:
        hub = self._hub(request)
        if hub is None:
            return _not_found()
        try:
            manager, device = self._device(hub, request)
            if set(request.query) - {"from", "days"}:
                raise GuestError("invalid", 422)
            try:
                start = date.fromisoformat(request.query.get("from", ""))
                days = int(request.query.get("days", "14"))
            except ValueError as err:
                raise GuestError("invalid", 422) from err
            result = await manager.async_waste_days(device, start, days)
        except GuestError as err:
            return _fail(err)
        return _json({"days": result})


class GuestWeatherView(_GuestView):
    """GET: today's weather line, when the adult turned it on."""

    url = f"{BASE}/api/weather"
    name = "api:family_hub:guest:weather"

    async def get(self, request: web.Request) -> web.Response:
        hub = self._hub(request)
        if hub is None:
            return _not_found()
        try:
            manager, device = self._device(hub, request)
            result = await manager.async_weather(device)
        except GuestError as err:
            return _fail(err)
        return _json(result)


def register_views(hass: HomeAssistant) -> None:
    """Called once, when the first invite or device exists (see GuestHub.ensure_views)."""
    access = logging.getLogger("aiohttp.access")
    if HIDE_INVITE not in access.filters:
        access.addFilter(HIDE_INVITE)
    # The API first: the file view's {name} would otherwise be tried for "api".
    for view in (
        GuestActivateView(),
        GuestMeView(),
        GuestEventsView(),
        GuestEventView(),
        GuestPushView(),
        GuestShiftsView(),
        GuestShiftActionView(),
        GuestListView(),
        GuestWasteView(),
        GuestWeatherView(),
        GuestPageView(),
        GuestFileView(),
    ):
        hass.http.register_view(view)
