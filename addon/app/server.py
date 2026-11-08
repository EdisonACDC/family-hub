"""Family Hub tablet UI: web server behind Ingress, relaying to Home Assistant.

Browser --(Ingress, WebSocket /ws)--> this server --(WebSocket, supervisor token)--> Home Assistant

- Only requests coming from the Ingress proxy are answered (anything else gets 403).
- The user is read from X-Remote-User-Id (set by Ingress) and mapped to a person's role.
- Only calendar.family_hub_* entities are subscribed to, and only family_hub actions
  are forwarded. Nothing is stored here.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

from . import importer
from .access import (
    ADULT,
    CHILD,
    GUEST,
    GUEST_IDENTITY,
    Identity,
    can_change,
    can_see,
    can_write,
    identify,
)
from .ha_link import HAClient, HAError
from .notify import echo_speakers, phone_services, settings_of
from .waste import WASTE_KINDS, waste_kind

LOGGER = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
CALENDAR_PREFIX = "calendar.family_hub_"
# Calendars from ICS files or links: calendar.family_hub_ext_<id>, read only.
EXT_PREFIX = "calendar.family_hub_ext_"
MAX_ICS_BYTES = 5 * 1024 * 1024
DOMAIN = "family_hub"
INGRESS_PEER_DEFAULT = "172.30.32.2"
USER_HEADER = "X-Remote-User-Id"
USER_COOKIE = "fh_user"
# The only actions the browser may call. Anything else is refused.
ALLOWED_SERVICES = frozenset(
    {"add_event", "update_event", "delete_event", "move_event", "snooze_reminder", "stop_reminder"}
)
# Actions that act on one existing event, so the event must belong to the user (children).
EVENT_SERVICES = frozenset(
    {"update_event", "delete_event", "move_event", "snooze_reminder", "stop_reminder"}
)
REMINDER_EVENTS = ("family_hub_reminder", "family_hub_reminder_closed")
SYNC_SECONDS = 30
LOOKUP_YEARS = 3

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


class Hub:
    """Connects browsers (sockets) to Home Assistant (one HAClient)."""

    def __init__(self, ha: HAClient) -> None:
        self.ha = ha
        self.browsers: dict[web.WebSocketResponse, str | None] = {}
        self._entity_sub: int | None = None
        self._entity_ids: frozenset[str] = frozenset()
        self._tasks: set[asyncio.Task[None]] = set()
        ha.on_connection = self.on_ha_connection

    # ---- connection and subscriptions ----

    async def on_ha_connection(self, connected: bool) -> None:
        self._entity_sub = None
        self._entity_ids = frozenset()
        if connected:
            for event_type in REMINDER_EVENTS:
                await self.ha.subscribe("subscribe_events", self.on_reminder, event_type=event_type)
            await self.sync_entities()
        await self.broadcast({"type": "connection", "connected": connected})

    def schedule_resync(self) -> None:
        """Calendars created by the guide appear after the entry reloads: subscribe to them soon."""
        task = asyncio.create_task(self._resync_soon())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _resync_soon(self) -> None:
        await asyncio.sleep(2)
        with contextlib.suppress(HAError):
            await self.sync_entities()

    async def sync_entities(self) -> None:
        """Subscribe to the family calendars and the external sources the guide chose, and
        nothing else. The list is kept current."""
        ids = frozenset(await self.watched_ids())
        if ids == self._entity_ids and self._entity_sub is not None:
            return
        if self._entity_sub is not None:
            await self.ha.unsubscribe(self._entity_sub)
            self._entity_sub = None
        if ids:
            self._entity_sub = await self.ha.subscribe(
                "subscribe_entities", self.on_entities, entity_ids=sorted(ids)
            )
        self._entity_ids = ids

    async def on_entities(self, event: dict[str, Any]) -> None:
        changed = [*event.get("c", {}), *event.get("r", [])]
        for entity_id in changed:
            if entity_id in self._entity_ids:
                await self.broadcast({"type": "state_changed", "entity_id": entity_id})

    async def on_reminder(self, event: dict[str, Any]) -> None:
        event_type = event.get("event_type")
        if event_type not in REMINDER_EVENTS:
            return
        data = event.get("data", {})
        message = {"type": "event", "event_type": event_type, "data": data}
        for ws, user in list(self.browsers.items()):
            identity = await self.identity_for(user)
            if identity.role == CHILD:
                owners = await self.owner_ids(str(data.get("uid", "")))
                if owners is None or not can_see(identity, owners):
                    continue
            elif identity.role not in ("adult", "shared"):
                continue  # guests get no popups: they cannot act on them
            await self._send(ws, message)

    async def broadcast(self, message: dict[str, Any]) -> None:
        for ws in list(self.browsers):
            await self._send(ws, message)

    async def _send(self, ws: web.WebSocketResponse, message: dict[str, Any]) -> None:
        try:
            await ws.send_json(message)
        except ConnectionError:
            self.browsers.pop(ws, None)

    # ---- Home Assistant reads ----

    async def _states(self) -> list[dict[str, Any]]:
        return list(await self.ha.call("get_states"))

    async def calendar_styles(self) -> dict[str, dict[str, str]]:
        """Name, type and colour the family gave the calendars of Home Assistant."""
        try:
            config = await self.ha.call("family_hub/config/get")
        except HAError:
            return {}
        return dict(config.get("sources", {}).get("calendar_styles", {}))

    async def sources(self) -> dict[str, list[str]]:
        """The external entities the guide chose: {"todo": [...], "calendars": [...]}."""
        try:
            config = await self.ha.call("family_hub/config/get")
        except HAError:
            return {"todo": [], "calendars": [], "weather": []}
        chosen = config.get("sources", {})
        return {
            "todo": list(chosen.get("todo", [])),
            "calendars": list(chosen.get("calendars", [])),
            "weather": list(chosen.get("weather", [])),
        }

    async def watched_ids(self) -> list[str]:
        sources = await self.sources()
        family = [c["entity_id"] for c in await self.family_calendars()]
        ext = [f"{EXT_PREFIX}{e['id']}" for e in (await self.ics_info())["calendars"]]
        return sorted({*family, *sources["todo"], *sources["calendars"], *sources["weather"], *ext})

    async def family_calendars(self) -> list[dict[str, Any]]:
        found = []
        for state in await self._states():
            entity_id = state["entity_id"]
            if not entity_id.startswith(CALENDAR_PREFIX) or entity_id.startswith(EXT_PREFIX):
                continue
            attributes = state.get("attributes", {})
            found.append(
                {
                    "entity_id": entity_id,
                    "name": attributes.get("friendly_name", entity_id),
                    "category_id": attributes.get("category_id", ""),
                    "external": False,
                    "persons": list(attributes.get("persons", [])),
                }
            )
        return found

    async def calendars(self) -> list[dict[str, Any]]:
        """Family calendars, then the external calendars the guide chose (read only)."""
        found = await self.family_calendars()
        external = (await self.sources())["calendars"]
        styles = await self.calendar_styles()
        names = {
            s["entity_id"]: s.get("attributes", {}).get("friendly_name")
            for s in await self._states()
        }
        for entity_id in external:
            style = styles.get(entity_id, {})
            # The name the family chose, else the friendly name, else the entity id made readable.
            name = style.get("name") or names.get(entity_id) or readable_name(entity_id)
            found.append(
                {
                    "entity_id": entity_id,
                    "name": name,
                    "category_id": "",
                    "external": True,
                    "type": style.get("type", "altro"),
                    "color": style.get("color", "#64748B"),
                }
            )
        # Calendars from ICS files or links (read only): calendar.family_hub_ext_<id>.
        info = await self.ics_info()
        for entry in info["calendars"]:
            entity_id = f"{EXT_PREFIX}{entry['id']}"
            if entity_id in names:
                found.append(
                    {
                        "entity_id": entity_id,
                        "name": entry["name"],
                        "category_id": "",
                        "external": True,
                        "type": entry.get("type", "altro"),
                        "color": entry.get("color", "#64748B"),
                        "waste_colors": info["waste_styles"],
                    }
                )
        return found

    async def ics_info(self) -> dict[str, Any]:
        """The external calendars Family Hub keeps, and the colour of each rubbish kind.
        Empty if Home Assistant cannot say."""
        try:
            result = await self.ha.call("family_hub/ics/list")
        except HAError:
            return {"calendars": [], "waste_styles": {}}
        styles = {k: str(v["color"]) for k, v in WASTE_KINDS.items()}
        styles.update({str(k): str(v) for k, v in dict(result.get("waste_styles", {})).items()})
        return {"calendars": list(result.get("calendars", [])), "waste_styles": styles}

    # ---- external calendars (ICS): adults only ----

    async def ics_op(self, identity: Identity, op: str, request: dict[str, Any]) -> Any:
        """Add, change, refresh, replace and remove external calendars. Only adults; the
        integration checks the file and the link, and keeps nothing that is not valid."""
        if identity.role != ADULT:
            raise PermissionError(op)
        if op == "ics_list":
            return await self.ha.call("family_hub/ics/list")
        if op == "ics_styles":
            return await self.ha.call("family_hub/ics/styles", styles=dict(request["styles"]))
        if op == "ics_remove":
            result = await self.ha.call(
                "family_hub/ics/remove", calendar_id=str(request["calendar_id"])
            )
        elif op == "ics_refresh":
            result = await self.ha.call(
                "family_hub/ics/refresh", calendar_id=str(request["calendar_id"])
            )
        else:
            if (
                op in ("ics_add", "ics_replace")
                and "content" in request
                and (len(str(request["content"]).encode("utf-8")) > MAX_ICS_BYTES)
            ):
                raise HAError("too large", "too_large")
            if op == "ics_add":
                payload: dict[str, Any] = {"calendar": dict(request["calendar"])}
                if "url" in request:
                    payload["url"] = str(request["url"])
                if "content" in request:
                    payload["content"] = str(request["content"])
                result = await self.ha.call("family_hub/ics/add", **payload)
            elif op == "ics_update":
                result = await self.ha.call(
                    "family_hub/ics/update",
                    calendar_id=str(request["calendar_id"]),
                    calendar=dict(request["calendar"]),
                )
            else:
                result = await self.ha.call(
                    "family_hub/ics/replace",
                    calendar_id=str(request["calendar_id"]),
                    content=str(request["content"]),
                )
        self.schedule_resync()
        return result

    async def candidate_entities(self) -> list[dict[str, str]]:
        """To-do lists and calendars (not Family Hub's own) that the guide may offer."""
        found = []
        for state in await self._states():
            entity_id = state["entity_id"]
            domain = entity_id.split(".", 1)[0]
            if domain not in ("todo", "calendar", "weather") or entity_id.startswith(
                CALENDAR_PREFIX
            ):
                continue
            found.append(
                {
                    "entity_id": entity_id,
                    "name": state.get("attributes", {}).get("friendly_name") or entity_id,
                    "domain": domain,
                }
            )
        return found

    # ---- shifts ----

    async def shifts_op(self, identity: Identity, op: str, request: dict[str, Any]) -> Any:
        """Shift models and the shift calendar. Adults handle everyone's shifts; a child only
        their own; a guest nothing."""
        if identity.role == GUEST:
            raise PermissionError(op)
        if op == "shifts":
            config = await self.ha.call("family_hub/config/get")
            shifts = config.get("shifts", {})
            persons = config.get("persons", [])
            if identity.role == CHILD:
                shifts = {k: v for k, v in shifts.items() if k == identity.person_id}
                persons = [p for p in persons if p["id"] == identity.person_id]
            return {
                "shifts": shifts,
                "categories": config.get("categories", []),
                "persons": [{"id": p["id"], "name": p["name"]} for p in persons],
                "time_format": config.get("family", {}).get("time_format", "24h"),
            }
        person = str(request["person"])
        if identity.role == CHILD and identity.person_id != person:
            raise PermissionError(op)
        if op == "shifts_save":
            return await self.save_shifts(request, person)
        return await self.apply_shift(identity, request, person)

    async def save_shifts(self, request: dict[str, Any], person: str) -> dict[str, Any]:
        """Save the models. When a time changed and events exist from tomorrow on, the first
        call answers with how many, so the tablet can ask; the second call says yes or no."""
        shifts = request["shifts"]
        if not isinstance(shifts, list):
            raise TypeError("shifts must be a list")
        apply_future = request.get("apply_future")
        config = await self.ha.call("family_hub/config/get")
        old = {s["id"]: s for s in config.get("shifts", {}).get(person, [])}
        changed = [
            s["id"]
            for s in shifts
            if isinstance(s, dict)
            and s.get("id") in old
            and _shift_fields(s) != _shift_fields(old[s["id"]])
        ]
        if changed and apply_future is None:
            count = len(await self.future_shift_events(person, changed))
            if count:
                return {"confirm": count}
        await self.ha.call(
            "family_hub/shifts/save",
            person=person,
            shifts=shifts,
            apply_future=bool(apply_future),
        )
        return {"saved": True}

    async def future_shift_events(self, person: str, shift_ids: list[str]) -> list[dict[str, Any]]:
        """Events from tomorrow on, made from the given models, for this person."""
        now = datetime.now()
        start = (now + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")
        end = (now + timedelta(days=365 * LOOKUP_YEARS)).strftime("%Y-%m-%d 00:00:00")
        found = []
        for calendar in await self.family_calendars():
            for raw in await self._events_of(calendar["entity_id"], start, end):
                if raw.get("shift_id") in shift_ids and person in _owners(raw):
                    found.append(raw)
        return found

    async def shift_events_on(self, person: str, day: str) -> list[dict[str, Any]]:
        """This person's shift events on one day."""
        start = f"{day} 00:00:00"
        end = (date.fromisoformat(day) + timedelta(days=1)).isoformat() + " 00:00:00"
        found = []
        for calendar in await self.family_calendars():
            for raw in await self._events_of(calendar["entity_id"], start, end):
                if raw.get("shift_id") and person in _owners(raw):
                    found.append(raw)
        return found

    async def apply_shift(
        self, identity: Identity, request: dict[str, Any], person: str
    ) -> dict[str, int]:
        """Put a shift on the chosen days (replacing this person's shift on each day), or
        take it off when no shift is given."""
        days = request["days"]
        if not isinstance(days, list) or not 1 <= len(days) <= 62:
            raise ValueError("days")
        days = sorted({str(d) for d in days})
        for day in days:
            date.fromisoformat(day)  # ValueError if not a date
        shift_id = str(request.get("shift_id") or "")
        shift = None
        if shift_id:
            config = await self.ha.call("family_hub/config/get")
            shift = next(
                (s for s in config.get("shifts", {}).get(person, []) if s["id"] == shift_id),
                None,
            )
            if shift is None:
                raise LookupError(shift_id)
        removed = inserted = 0
        for day in days:
            for raw in await self.shift_events_on(person, day):
                await self.ha.call(
                    "call_service",
                    domain=DOMAIN,
                    service="delete_event",
                    service_data={"uid": raw["record_id"]},
                )
                removed += 1
            if shift is not None:
                end_day = day
                if shift["end"] < shift["start"]:
                    end_day = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
                await self.ha.call(
                    "call_service",
                    domain=DOMAIN,
                    service="add_event",
                    service_data={
                        "category": shift["category"],
                        "summary": shift["name"],
                        "start": f"{day} {shift['start']}:00",
                        "end": f"{end_day} {shift['end']}:00",
                        "persons": [person],
                        "shift_id": shift["id"],
                    },
                )
                inserted += 1
        return {"removed": removed, "inserted": inserted}

    async def todo_lists(self) -> list[dict[str, str]]:
        """The to-do lists the guide chose, with their names."""
        names = {
            s["entity_id"]: s.get("attributes", {}).get("friendly_name")
            for s in await self._states()
        }
        return [
            {"entity_id": entity_id, "name": names.get(entity_id) or entity_id}
            for entity_id in (await self.sources())["todo"]
        ]

    async def check_source(self, kind: str, entity_id: str) -> None:
        """Only the entities the guide chose may be read or changed from the tablet."""
        if entity_id not in (await self.sources())[kind]:
            raise PermissionError(entity_id)

    async def persons(self) -> list[dict[str, Any]]:
        for state in await self._states():
            if state["entity_id"].startswith(CALENDAR_PREFIX):
                return list(state.get("attributes", {}).get("persons", []))
        return []

    async def theme(self) -> str:
        """The screen theme chosen in the setup guide ("auto" when unknown)."""
        try:
            config = await self.ha.call("family_hub/config/get")
        except HAError:
            return "auto"
        return str(config.get("screen", {}).get("theme", "auto"))

    async def first_weekday(self) -> str:
        """The first day of the week in the family's settings: "monday" or "sunday"."""
        try:
            config = await self.ha.call("family_hub/config/get")
        except HAError:
            return "monday"
        value = str(config.get("family", {}).get("first_weekday", "monday"))
        return value if value in ("monday", "sunday") else "monday"

    async def time_format(self) -> str:
        """The family's clock: "24h" or "12h", chosen in the setup guide. Every time on the
        screen follows it, not the browser's own setting."""
        try:
            config = await self.ha.call("family_hub/config/get")
        except HAError:
            return "24h"
        value = str(config.get("family", {}).get("time_format", "24h"))
        return value if value in ("24h", "12h") else "24h"

    async def admin_ids(self) -> set[str]:
        """Home Assistant users in the system-admin group."""
        users = await self.ha.call("config/auth/list")
        return {u["id"] for u in users if "system-admin" in u.get("group_ids", [])}

    async def user_name(self, user_id: str | None) -> str:
        """The name of the Home Assistant user in front of the screen, for the guest notice."""
        if not user_id or not self.ha.connected:
            return ""
        try:
            users = await self.ha.call("config/auth/list")
        except HAError:
            return ""
        for user in users:
            if user["id"] == user_id:
                return str(user.get("name") or "")
        return ""

    async def identity_for(self, user_id: str | None) -> Identity:
        """Who is in front of the screen.

        A person's Home Assistant user gives that person's role. A shared screen (a user listed
        as shared in the settings) acts as an adult for events and lists. Any other
        administrator of Home Assistant is an adult, linked to a person or not (so the family's
        own tablet, logged in as the admin, is never a guest). Everyone else is a guest."""
        if not self.ha.connected:
            return GUEST_IDENTITY
        try:
            states = await self._states()
            calendar = next((s for s in states if s["entity_id"].startswith(CALENDAR_PREFIX)), {})
            attributes = calendar.get("attributes", {})
            persons = list(attributes.get("persons", []))
            shared = list(attributes.get("shared_users", []))
            linked = identify(user_id, persons, shared)
            if linked.role != GUEST or linked.person_id is not None:
                return linked
            if user_id and user_id in await self.admin_ids():
                return Identity(ADULT, None)
            return GUEST_IDENTITY
        except HAError:
            return GUEST_IDENTITY

    async def weather(self) -> dict[str, Any] | None:
        """The weather entity the guide chose: its state now and the daily forecast.

        Read only, and everyone may read it (like the to-do lists the guide chose). The entity
        must be the one in the guide's sources; anything else is never read."""
        chosen = (await self.sources())["weather"]
        if not chosen:
            return None
        entity_id = chosen[0]
        state = next((s for s in await self._states() if s["entity_id"] == entity_id), None)
        if state is None:
            return None
        attributes = state.get("attributes", {})
        return {
            "entity_id": entity_id,
            "condition": str(state.get("state", "")),
            "temperature": attributes.get("temperature"),
            "unit": str(attributes.get("temperature_unit", "°C")),
            "forecast": await self._forecast_of(entity_id),
        }

    async def _forecast_of(self, entity_id: str) -> list[dict[str, Any]]:
        """The daily forecast, with a short subscription. Missing forecasts give an empty list."""
        future: asyncio.Future[list[dict[str, Any]]] = asyncio.get_running_loop().create_future()

        async def handler(event: dict[str, Any]) -> None:
            if not future.done():
                future.set_result(list(event.get("forecast", [])))

        try:
            sub = await self.ha.subscribe(
                "weather/subscribe_forecast", handler, entity_id=entity_id, forecast_type="daily"
            )
        except HAError:
            return []
        try:
            return await asyncio.wait_for(future, timeout=15)
        except TimeoutError:
            return []
        finally:
            await self.ha.unsubscribe(sub)

    async def _events_of(self, entity_id: str, start: str, end: str) -> list[dict[str, Any]]:
        """Read one calendar's events for a window with a short subscription."""
        future: asyncio.Future[list[dict[str, Any]]] = asyncio.get_running_loop().create_future()

        async def handler(event: dict[str, Any]) -> None:
            if not future.done():
                future.set_result(event.get("events", []))

        sub = await self.ha.subscribe(
            "calendar/event/subscribe", handler, entity_id=entity_id, start=start, end=end
        )
        try:
            return await asyncio.wait_for(future, timeout=15)
        finally:
            await self.ha.unsubscribe(sub)

    async def events(
        self, start: str, end: str, identity: Identity
    ) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for calendar in await self.calendars():
            entity_id = calendar["entity_id"]
            visible = []
            if calendar["external"]:
                # External calendars are shown to everyone and never changed from here.
                # Rubbish pickups carry their kind and colour, read from the title.
                for raw in await self._events_of(entity_id, start, end):
                    item: dict[str, Any] = {
                        "summary": raw.get("summary", ""),
                        "start": raw.get("start", ""),
                        "end": raw.get("end", ""),
                        "location": raw.get("location", ""),
                        "record_id": "",
                        "person_ids": [],
                        "external": True,
                    }
                    if calendar.get("type") == "rifiuti":
                        kind = waste_kind(str(raw.get("summary", "")))
                        if kind is not None:
                            item["waste"] = kind
                            item["waste_color"] = calendar["waste_colors"].get(
                                kind, calendar["color"]
                            )
                    visible.append(item)
                result[entity_id] = visible
                continue
            for raw in await self._events_of(entity_id, start, end):
                owners = _owners(raw)
                if not can_see(identity, owners):
                    continue
                visible.append(
                    {
                        "summary": raw.get("summary", ""),
                        "start": raw.get("start", ""),
                        "end": raw.get("end", ""),
                        "location": raw.get("location", ""),
                        "record_id": raw.get("record_id", ""),
                        "person_ids": owners,
                        "shift_id": raw.get("shift_id", ""),
                        "description": raw.get("description") or "",
                        "reminder_offsets": raw.get("reminder_offsets", "default"),
                        "category_id": calendar.get("category_id", ""),
                        "calendar": calendar.get("name", ""),
                    }
                )
            result[entity_id] = visible
        return result

    async def owner_ids(self, uid: str) -> list[str] | None:
        """The persons of one event, or None if the event does not exist."""
        if not uid:
            return None
        now = datetime.now()
        start = (now - timedelta(days=365 * LOOKUP_YEARS)).strftime("%Y-%m-%d 00:00:00")
        end = (now + timedelta(days=365 * LOOKUP_YEARS)).strftime("%Y-%m-%d 00:00:00")
        for calendar in await self.family_calendars():
            for raw in await self._events_of(calendar["entity_id"], start, end):
                if raw.get("record_id") == uid:
                    return _owners(raw)
        return None

    # ---- requests from browsers ----

    async def handle(self, request: dict[str, Any], user_id: str | None) -> dict[str, Any]:
        """Answer one request from a browser. Errors are returned, not raised."""
        op = request.get("op")
        identity = await self.identity_for(user_id)
        try:
            if op == "identity":
                return {"ok": True, "result": identity.as_dict()}
            if op == "calendars":
                return {"ok": True, "result": await self.calendars()}
            if op == "events":
                start, end = str(request["start"]), str(request["end"])
                return {"ok": True, "result": await self.events(start, end, identity)}
            if op in ("config_get", "config_save"):
                identity = await self.identity_for(user_id)
                if identity.role != ADULT:
                    raise PermissionError(op)
                if op == "config_get":
                    return {"ok": True, "result": await self.ha.call("family_hub/config/get")}
                config = request.get("config")
                if not isinstance(config, dict):
                    raise TypeError("config must be an object")
                await self.ha.call("family_hub/config/save", config=config)
                self.schedule_resync()
                theme = str(config.get("screen", {}).get("theme", "auto"))
                await self.broadcast(
                    {
                        "type": "theme",
                        "theme": theme,
                        "time_format": await self.time_format(),
                        "first_weekday": await self.first_weekday(),
                    }
                )
                return {"ok": True}
            if op == "service":
                await self.service(identity, str(request["service"]), request.get("data", {}))
                return {"ok": True}
            if op in ("shifts", "shifts_save", "shifts_apply"):
                return {"ok": True, "result": await self.shifts_op(identity, op, request)}
            if op in (
                "ics_list",
                "ics_add",
                "ics_update",
                "ics_refresh",
                "ics_replace",
                "ics_remove",
                "ics_styles",
            ):
                return {"ok": True, "result": await self.ics_op(identity, op, request)}
            if op in ("notify_get", "notify_save", "notify_test", "shared_save"):
                return {"ok": True, "result": await self.notify_op(identity, op, request)}
            if op == "weather":
                # Read only, for everyone: the screen shows the weather to guests too.
                return {"ok": True, "result": await self.weather()}
            if op == "todo_lists":
                return {"ok": True, "result": await self.todo_lists()}
            if op == "entities":
                if identity.role != ADULT:
                    raise PermissionError(op)
                return {"ok": True, "result": await self.candidate_entities()}
            if op in ("todo_items", "todo_add", "todo_update", "todo_remove"):
                return {"ok": True, "result": await self.todo(identity, op, request)}
            if op in ("import_sources", "import_preview", "import_run"):
                return {"ok": True, "result": await self.import_op(identity, op, request)}
            return {"ok": False, "error": "bad_request"}
        except PermissionError:
            return {"ok": False, "error": "forbidden"}
        except LookupError:
            return {"ok": False, "error": "not_found"}
        except HAError as err:
            # "error" is a code the guide translates; "detail" is HA's text, for logs.
            return {"ok": False, "error": err.code, "detail": str(err)}
        except (KeyError, ValueError, TypeError):
            return {"ok": False, "error": "bad_request"}

    # ---- notification settings ("Avvisi") ----

    async def notify_op(self, identity: Identity, op: str, request: dict[str, Any]) -> Any:
        """Who gets which notifications. Adults handle everyone's; each person their own;
        guests nothing. Home Assistant checks that the services exist when saving."""
        if identity.role == GUEST:
            raise PermissionError(op)
        if op == "notify_get":
            return await self.notify_settings(identity)
        if op == "notify_save":
            return await self.save_notify(identity, request)
        if op == "shared_save":
            return await self.save_shared(identity, request)
        return await self.notify_test(identity, request)

    async def notify_settings(self, identity: Identity) -> dict[str, Any]:
        config = await self.ha.call("family_hub/config/get")
        persons = list(config.get("persons", []))
        if identity.role == CHILD:
            persons = [p for p in persons if p["id"] == identity.person_id]
        result: dict[str, Any] = {
            "persons": [settings_of(p) for p in persons],
            "services": {
                "phone": phone_services(await self.ha.call("get_services")),
                "alexa": echo_speakers(
                    await self.ha.call("config/entity_registry/list"),
                    await self.ha.call("get_states"),
                ),
            },
            "time_format": config.get("family", {}).get("time_format", "24h"),
        }
        if identity.role == ADULT:
            users = await self.ha.call("config/auth/list")
            result["users"] = [
                {"id": u["id"], "name": u.get("name") or u["id"]}
                for u in users
                if not u.get("system_generated")
            ]
            result["shared_users"] = list(config.get("shared_users", []))
        return result

    async def save_shared(self, identity: Identity, request: dict[str, Any]) -> dict[str, Any]:
        """Which Home Assistant users are shared screens. Only adults; the integration keeps
        only users that are not linked to a person."""
        if identity.role != ADULT:
            raise PermissionError("shared_save")
        users = [str(u) for u in request["users"]]
        result: dict[str, Any] = await self.ha.call("family_hub/shared/save", users=users)
        return result

    async def save_notify(self, identity: Identity, request: dict[str, Any]) -> dict[str, Any]:
        persons = request["persons"]
        if not isinstance(persons, dict):
            raise TypeError("persons must be an object")
        if identity.role == CHILD:
            # A child changes their own channels, services, volume and quiet hours, nothing else.
            if set(persons) - {identity.person_id}:
                raise PermissionError("notify_save")
            if any("ha_user_id" in changes for changes in persons.values()):
                raise PermissionError("notify_save")
        await self.ha.call("family_hub/notify/save", persons=persons)
        self.schedule_resync()
        return {"saved": True}

    async def notify_test(self, identity: Identity, request: dict[str, Any]) -> dict[str, Any]:
        """Ask the integration for a test message to this person's chosen services only.
        It answers no_service when none is chosen or the chosen one no longer exists."""
        person_id = str(request["person"])
        if identity.role == CHILD and identity.person_id != person_id:
            raise PermissionError("notify_test")
        result: dict[str, Any] = await self.ha.call(
            "family_hub/notify/test", person=person_id, kind=str(request["kind"])
        )
        return result

    async def todo(self, identity: Identity, op: str, request: dict[str, Any]) -> Any:
        """To-do lists the guide chose. Everyone reads; adults and children add and tick;
        only adults remove."""
        entity_id = str(request["entity_id"])
        await self.check_source("todo", entity_id)
        if op == "todo_items":
            result = await self.ha.call("todo/item/list", entity_id=entity_id)
            return list(result.get("items", []))
        if not can_write(identity):
            raise PermissionError(op)
        if op == "todo_add":
            summary = str(request["summary"]).strip()
            if not summary or len(summary) > 255:
                raise ValueError("summary")
            await self.ha.call(
                "call_service",
                domain="todo",
                service="add_item",
                service_data={"entity_id": entity_id, "item": summary},
            )
            return None
        if op == "todo_update":
            status = "completed" if request["done"] else "needs_action"
            await self.ha.call(
                "call_service",
                domain="todo",
                service="update_item",
                service_data={
                    "entity_id": entity_id,
                    "item": str(request["item"]),
                    "status": status,
                },
            )
            return None
        if identity.role != ADULT:  # todo_remove
            raise PermissionError(op)
        await self.ha.call(
            "call_service",
            domain="todo",
            service="remove_item",
            service_data={"entity_id": entity_id, "item": [str(request["item"])]},
        )
        return None

    # ---- importing old calendars (adults only) ----

    async def import_op(self, identity: Identity, op: str, request: dict[str, Any]) -> Any:
        """Copy an old Home Assistant calendar into a Family Hub category. Preview first; the
        copy skips events that are already in the category, so it can be repeated safely."""
        if identity.role != ADULT:
            raise PermissionError(op)
        if op == "import_sources":
            return [c for c in await self.candidate_entities() if c["domain"] == "calendar"]
        entity_id = str(request["entity_id"])
        if not entity_id.startswith("calendar.") or entity_id.startswith(CALENDAR_PREFIX):
            raise ValueError("entity_id")
        category_id = str(request["category_id"])
        target = next(
            (c for c in await self.family_calendars() if c["category_id"] == category_id), None
        )
        if target is None:
            raise LookupError(category_id)
        person = str(request.get("person") or "")
        if person and person not in {str(p["id"]) for p in await self.persons()}:
            raise LookupError(person)
        now = datetime.now()
        start = (now - timedelta(days=importer.PAST_DAYS)).strftime("%Y-%m-%d 00:00:00")
        end = (now + timedelta(days=365 * importer.FUTURE_YEARS)).strftime("%Y-%m-%d 00:00:00")
        source = await self._events_of(entity_id, start, end)
        existing = await self._events_of(target["entity_id"], start, end)
        to_copy, skipped = importer.plan(source, existing)
        if op == "import_preview":
            return {
                "total": len(to_copy),
                "skipped": skipped,
                "items": [
                    {
                        "summary": e.get("summary", ""),
                        "start": e.get("start", ""),
                        "end": e.get("end", ""),
                    }
                    for e in to_copy[: importer.PREVIEW_COUNT]
                ],
            }
        persons = [person] if person else []
        for event in to_copy:
            # One event at a time: if one fails, the rest stays to copy and nothing repeats.
            await self.ha.call(
                "call_service",
                domain=DOMAIN,
                service="add_event",
                service_data=importer.service_data(event, category_id, persons),
            )
        return {"copied": len(to_copy), "skipped": skipped}

    async def service(self, identity: Identity, service: str, data: Any) -> None:
        if service not in ALLOWED_SERVICES:
            raise ValueError(service)
        if not isinstance(data, dict):
            raise TypeError("data must be an object")
        if not can_write(identity):
            raise PermissionError(service)
        if service == "add_event":
            if identity.role == CHILD:
                data = {**data, "persons": [identity.person_id]}
        elif service in EVENT_SERVICES and identity.role != ADULT:
            owners = await self.owner_ids(str(data["uid"]))
            if owners is None:
                raise LookupError(data["uid"])
            if not can_change(identity, owners):
                raise PermissionError(service)
            if service == "update_event" and identity.role == CHILD and "persons" in data:
                raise PermissionError("children cannot change the persons of an event")
        await self.ha.call("call_service", domain=DOMAIN, service=service, service_data=data)


def _shift_fields(shift: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
    return (shift.get("name"), shift.get("start"), shift.get("end"), shift.get("category"))


def readable_name(entity_id: str) -> str:
    """calendar.weekend_festivi_bw -> "Weekend Festivi Bw": a name for an id with no name."""
    return entity_id.split(".", 1)[-1].replace("_", " ").title()


def _owners(raw: dict[str, Any]) -> list[str]:
    return [p for p in str(raw.get("person_ids", "")).split(",") if p]


# ---- web layer ----

HUB = web.AppKey("hub", Hub)
PEERS = web.AppKey("allowed_peers", frozenset)
HA_TASK = web.AppKey("ha_task", asyncio.Task)
SYNC_TASK = web.AppKey("sync_task", asyncio.Task)


@web.middleware
async def ingress_only(request: web.Request, handler: Handler) -> web.StreamResponse:
    """Refuse everything that does not come from the Ingress proxy."""
    if request.remote not in request.app[PEERS]:
        raise web.HTTPForbidden(text="Family Hub is only available through Home Assistant.")
    return await handler(request)


async def _ws_handler(request: web.Request) -> web.WebSocketResponse:
    hub: Hub = request.app[HUB]
    # A file of up to 5 MB arrives in one message: the limit is set above it.
    ws = web.WebSocketResponse(heartbeat=30, max_msg_size=8 * 1024 * 1024)
    await ws.prepare(request)
    user_id = _user_of(request)
    hub.browsers[ws] = user_id
    identity = await hub.identity_for(user_id)
    await ws.send_json(
        {"type": "identity", **identity.as_dict(), "user_name": await hub.user_name(user_id)}
    )
    await ws.send_json({"type": "connection", "connected": hub.ha.connected})
    await ws.send_json(
        {
            "type": "theme",
            "theme": await hub.theme(),
            "time_format": await hub.time_format(),
            "first_weekday": await hub.first_weekday(),
        }
    )
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                break
            request_json = msg.json()
            reply = await hub.handle(request_json, user_id)
            reply["id"] = request_json.get("id")
            reply["type"] = "result"
            await ws.send_json(reply)
    finally:
        hub.browsers.pop(ws, None)
    return ws


def test_cookie_enabled() -> bool:
    """The cookie fallback exists only for browser tests (FH_TEST_COOKIE=1), never in production."""
    return os.environ.get("FH_TEST_COOKIE") == "1"


def _user_of(request: web.Request) -> str | None:
    """The Home Assistant user: the Ingress header. In test mode only, a cookie can stand in
    for it, because Playwright cannot send extra headers on a WebSocket handshake."""
    user = request.headers.get(USER_HEADER)
    if user:
        return user
    if test_cookie_enabled():
        return request.cookies.get(USER_COOKIE) or None
    return None


async def _index(request: web.Request) -> web.FileResponse:
    response = web.FileResponse(STATIC_DIR / "index.html")
    user_id = request.headers.get(USER_HEADER)
    if user_id and test_cookie_enabled():
        response.set_cookie(USER_COOKIE, user_id, httponly=True, samesite="Strict", path="/")
    return response


async def _health(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def _sync_loop(hub: Hub) -> None:
    while True:
        await asyncio.sleep(SYNC_SECONDS)
        if hub.ha.connected:
            with contextlib.suppress(HAError):
                await hub.sync_entities()


def create_app(
    ha: HAClient, allowed_peers: frozenset[str] = frozenset({INGRESS_PEER_DEFAULT})
) -> web.Application:
    """Build the web application around an HAClient (started and stopped with the app)."""
    app = web.Application(middlewares=[ingress_only])
    app[HUB] = Hub(ha)
    app[PEERS] = allowed_peers

    async def start(app: web.Application) -> None:
        app[HA_TASK] = asyncio.create_task(ha.run())
        app[SYNC_TASK] = asyncio.create_task(_sync_loop(app[HUB]))

    async def stop(app: web.Application) -> None:
        for key in (SYNC_TASK, HA_TASK):
            task = app.get(key)
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    app.on_startup.append(start)
    app.on_cleanup.append(stop)
    app.router.add_get("/", _index)
    app.router.add_get("/health", _health)
    app.router.add_get("/ws", _ws_handler)
    app.router.add_static("/static/", STATIC_DIR, show_index=False)
    return app


def config_from_env() -> tuple[str, str, int, frozenset[str]]:
    """URL, token, port and the Ingress proxy address(es)."""
    url = os.environ.get("HA_WS_URL", "ws://supervisor/core/websocket")
    token = os.environ.get("SUPERVISOR_TOKEN") or os.environ.get("HA_TOKEN", "")
    port = int(os.environ.get("PORT", "8099"))
    peers = frozenset(
        p.strip()
        for p in os.environ.get("INGRESS_PEERS", INGRESS_PEER_DEFAULT).split(",")
        if p.strip()
    )
    return url, token, port, peers


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    url, token, port, peers = config_from_env()
    if not token:
        # Only the names are logged, never the values.
        names = sorted(k for k in os.environ if k.startswith(("SUPERVISOR", "HA_")))
        LOGGER.error(
            "No token: SUPERVISOR_TOKEN is missing. Variables present (names only): %s",
            ", ".join(names) or "none",
        )
        raise SystemExit("No token: SUPERVISOR_TOKEN is missing")
    app = create_app(HAClient(url, token), peers)
    web.run_app(app, host="0.0.0.0", port=port, print=None)


if __name__ == "__main__":
    main()
