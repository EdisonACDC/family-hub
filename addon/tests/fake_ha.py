"""A small stand-in for Home Assistant's WebSocket API, for tests.

It implements only what the add-on uses: the auth handshake, get_states, subscribe_events,
subscribe_entities, calendar/event/subscribe, unsubscribe_events and call_service for
family_hub actions. Calls are recorded so tests can check what the add-on asked for.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

from aiohttp import WSMsgType, web
from app.waste import DEFAULT_WASTE_TYPES

TOKEN = "test-token"

# Who is who in the fake family. ``ha_user_id`` links a Home Assistant user to a person.
PERSONS = [
    {"id": "sofia", "name": "Sofia", "role": "child", "ha_user_id": "u-sofia"},
    {"id": "mamma", "name": "Mamma", "role": "adult", "ha_user_id": "u-mamma"},
    {"id": "ospite", "name": "Ospite", "role": "guest", "ha_user_id": "u-guest"},
]

FAMILY = "calendar.family_hub_famiglia"
SCHOOL = "calendar.family_hub_scuola"


def calendar_state(entity_id: str, name: str, category_id: str) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "state": "off",
        "attributes": {
            "friendly_name": name,
            "category_id": category_id,
            "persons": copy.deepcopy(PERSONS),
        },
    }


def notify_text(data: dict[str, Any]) -> str:
    """As the integration shows an event's own channels: "phone,alexa|all|80", or ""."""
    channels = data.get("channels")
    if channels is None:
        return ""
    volume = data.get("alexa_volume")
    return "|".join(
        [
            ",".join(channels),
            str(data.get("alexa_target") or ""),
            "" if volume is None else str(volume),
        ]
    )


def stored_event(
    summary: str, start: str, end: str, person_ids: str = "", record_id: str | None = None
) -> dict[str, Any]:
    return {
        "summary": summary,
        "start": start,
        "end": end,
        "description": "",
        "location": "",
        "person_ids": person_ids,
        "record_id": record_id or uuid.uuid4().hex,
        "shift_id": "",
        "notify": "",
    }


ADMIN_USER = "u-admin"
USERS = [
    {"id": "u-mamma", "name": "Mamma", "group_ids": ["system-users"]},
    {"id": "u-sofia", "name": "Sofia", "group_ids": ["system-users"]},
    {"id": "u-guest", "name": "Ospite", "group_ids": ["system-users"]},
    {"id": "u-stranger", "name": "Altro", "group_ids": ["system-users"]},
    {"id": ADMIN_USER, "name": "Admin", "group_ids": ["system-admin"]},
]


SHOP = "todo.spesa"
WASTE = "calendar.rifiuti"
WEATHER = "weather.home"


def weather_forecast() -> list[dict[str, Any]]:
    """Daily forecast: today and the next four days (today has the high and low)."""
    from datetime import date, timedelta

    today = date.today()
    return [
        {
            "datetime": f"{(today + timedelta(days=i)).isoformat()}T12:00:00+01:00",
            "condition": "cloudy" if i == 0 else "sunny",
            "temperature": 8.0 - i,
            "templow": 2.0 - i,
        }
        for i in range(5)
    ]


def external_states() -> list[dict[str, Any]]:
    return [
        {
            "entity_id": WEATHER,
            "state": "cloudy",
            "attributes": {"friendly_name": "Casa", "temperature": 5, "temperature_unit": "°C"},
        },
        {"entity_id": SHOP, "state": "2", "attributes": {"friendly_name": "Spesa"}},
        {"entity_id": WASTE, "state": "off", "attributes": {"friendly_name": "Rifiuti"}},
    ]


def default_config(configured: bool) -> dict[str, Any]:
    """What family_hub/config/get returns. A new install has no persons, as in the integration."""
    return {
        "configured": configured,
        "family": {
            "family_name": "Esempio",
            "language": "it",
            "first_weekday": "monday",
            "time_format": "24h",
            "country": "",
            "region": "",
        },
        "screen": {"theme": "auto"},
        "shifts": {},
        "sources": {
            "todo": [SHOP] if configured else [],
            "calendars": [WASTE] if configured else [],
            "weather": [WEATHER] if configured else [],
        },
        "persons": [
            {
                "id": p["id"],
                "name": p["name"],
                "color": "#2563EB",
                "role": p["role"],
                "ha_user_id": p["ha_user_id"],
            }
            for p in (PERSONS if configured else [])
        ],
        "categories": [
            {"id": "famiglia", "name": "Famiglia", "color": "#3B82F6"},
            {"id": "scuola", "name": "Scuola", "color": "#10B981"},
        ],
        "reminders": {
            "offsets": [30, 10],
            "channels": ["phone", "tablet"],
            "quiet_start": "22:00",
            "quiet_end": "07:00",
            "snooze_minutes": 10,
            "tts_entity": None,
            "morning_summary": "07:00",
            "evening_summary": "20:00",
            "all_day_reminder": "19:00",
        },
    }


# Notification services in the fake: phones, and the Alexa Media announcement service.
NOTIFY_SERVICES = ["mobile_app_sofia", "mobile_app_mamma", "alexa_media"]
# Echo speakers: media players of the alexa_media platform, as the entity registry lists them.
ECHO_SPEAKERS = ["media_player.kueche", "media_player.wohnzimmer"]


WASTE_KINDS = {
    "restmuell": {"label": "Restmüll", "icon": "trash", "color": "#374151"},
    "bio": {"label": "Bio", "icon": "leaf", "color": "#8B5A2B"},
    "papier": {"label": "Papier", "icon": "paper", "color": "#2563EB"},
    "gelb": {"label": "Gelber Sack", "icon": "bag", "color": "#EAB308"},
    "glas": {"label": "Glas", "icon": "bottle", "color": "#16A34A"},
}


class FakeHA:
    def __init__(self, calendars: bool = True) -> None:
        self.calls: list[dict[str, Any]] = []
        self.notify_saves: list[dict[str, Any]] = []
        self.notify_tests: list[dict[str, Any]] = []
        # External calendars (ICS): id -> the calendar as the integration keeps it.
        self.ics: dict[str, dict[str, Any]] = {}
        self.waste_types: list[dict[str, str]] = [dict(t) for t in DEFAULT_WASTE_TYPES]
        self.waste_styles: dict[str, str] = {t["id"]: t["color"] for t in self.waste_types}
        # Dashboards (url_path -> configuration); None is the default dashboard.
        self.dashboards: dict[str | None, dict[str, Any]] = {None: {"views": []}}
        self.notify_services: list[str] = list(NOTIFY_SERVICES)
        self.echos: list[str] = list(ECHO_SPEAKERS)
        self.config: dict[str, Any] = default_config(configured=calendars)
        self.states: list[dict[str, Any]] = [
            {"entity_id": "light.kitchen", "state": "on", "attributes": {"friendly_name": "Luce"}},
            *external_states(),
        ]
        self.todo_items: dict[str, list[dict[str, Any]]] = {
            SHOP: [
                {"uid": "latte", "summary": "Latte", "status": "needs_action"},
                {"uid": "pane", "summary": "Pane", "status": "completed"},
            ]
        }
        self.saved_configs: list[dict[str, Any]] = []
        self.shift_saves: list[dict[str, Any]] = []
        self.events: dict[str, list[dict[str, Any]]] = {}
        if calendars:
            self.states += [
                calendar_state(FAMILY, "Famiglia", "famiglia"),
                calendar_state(SCHOOL, "Scuola", "scuola"),
            ]
            self.events = {FAMILY: [], SCHOOL: []}
        self.events[WASTE] = [
            stored_event(
                "Ritiro indifferenziato", "2027-01-11T07:00:00+01:00", "2027-01-11T08:00:00+01:00"
            )
        ]
        # subscription id -> (socket, kind, filter)
        self._subs: dict[int, tuple[web.WebSocketResponse, str, Any]] = {}
        self._sockets: set[web.WebSocketResponse] = set()
        self.app = web.Application()
        self.app.router.add_get("/api/websocket", self._handle)

    # ---- test helpers (call them on the fake's own loop) ----

    async def push_event(self, event_type: str, data: dict[str, Any]) -> None:
        for sub_id, (ws, kind, wanted) in list(self._subs.items()):
            if kind == "events" and wanted == event_type:
                await self._send_event(ws, sub_id, {"event_type": event_type, "data": data})

    async def push_entity_change(self, entity_id: str) -> None:
        change = {"c": {entity_id: {"+": {"s": "off", "a": {}}}}}
        for sub_id, (ws, kind, _) in list(self._subs.items()):
            if kind == "entities":
                await self._send_event(ws, sub_id, change)

    async def add_event(
        self, entity_id: str, summary: str, start: str, end: str, person_ids: str = ""
    ) -> None:
        """Add an event as if another device had created it, then announce the change."""
        self.events[entity_id].append(stored_event(summary, start, end, person_ids))
        await self.push_entity_change(entity_id)

    async def drop_connections(self) -> None:
        for ws in list(self._sockets):
            await ws.close()

    # ---- protocol ----

    async def _handle(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        self._sockets.add(ws)
        try:
            await ws.send_json({"type": "auth_required", "ha_version": "2026.11.0"})
            auth = await ws.receive_json()
            if auth.get("access_token") != TOKEN:
                await ws.send_json({"type": "auth_invalid", "message": "Invalid access token"})
                return ws
            await ws.send_json({"type": "auth_ok", "ha_version": "2026.11.0"})
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    break
                await self._command(ws, msg.json())
        finally:
            for sub_id in [s for s, (w, _, _) in self._subs.items() if w is ws]:
                del self._subs[sub_id]
            self._sockets.discard(ws)
        return ws

    async def _command(self, ws: web.WebSocketResponse, msg: dict[str, Any]) -> None:
        kind = msg["type"]
        msg_id = msg["id"]
        if kind == "subscribe_events":
            self._subs[msg_id] = (ws, "events", msg.get("event_type"))
            await self._reply(ws, msg_id, True, None)
        elif kind == "subscribe_entities":
            self._subs[msg_id] = (ws, "entities", msg.get("entity_ids", []))
            await self._reply(ws, msg_id, True, None)
            initial = {"a": {e: {"s": "off", "a": {}} for e in msg.get("entity_ids", [])}}
            await self._send_event(ws, msg_id, initial)
        elif kind == "weather/subscribe_forecast":
            self._subs[msg_id] = (ws, "forecast", msg["entity_id"])
            await self._reply(ws, msg_id, True, None)
            await self._send_event(ws, msg_id, {"forecast": weather_forecast()})
        elif kind == "calendar/event/subscribe":
            self._subs[msg_id] = (ws, "calendar", msg["entity_id"])
            await self._reply(ws, msg_id, True, None)
            # Like Home Assistant: only events that start within the requested days.
            first, last = msg["start"][:10], msg["end"][:10]
            events = [
                copy.deepcopy(e)
                for e in self.events.get(msg["entity_id"], [])
                if first <= e["start"][:10] < last
            ]
            await self._send_event(ws, msg_id, {"events": events})
        elif kind == "unsubscribe_events":
            self._subs.pop(msg["subscription"], None)
            await self._reply(ws, msg_id, True, None)
        elif kind == "family_hub/shifts/save":
            self.shift_saves.append(copy.deepcopy(msg))
            shifts = []
            for item in msg["shifts"]:
                shifts.append({**item, "id": item.get("id") or uuid.uuid4().hex[:8]})
            self.config["shifts"][msg["person"]] = shifts
            await self._reply(ws, msg_id, True, {"saved": True, "updated": 0})
        elif kind == "todo/item/list":
            await self._reply(
                ws,
                msg_id,
                True,
                {"items": copy.deepcopy(self.todo_items.get(msg["entity_id"], []))},
            )
        elif kind == "config/auth/list":
            await self._reply(ws, msg_id, True, copy.deepcopy(USERS))
        elif kind == "get_services":
            notify = {name: {} for name in self.notify_services}
            await self._reply(ws, msg_id, True, {"notify": notify})
        elif kind == "family_hub/config/get":
            await self._reply(ws, msg_id, True, copy.deepcopy(self.config))
        elif kind == "family_hub/config/save":
            await self._save_config(ws, msg)
        elif kind == "family_hub/notify/save":
            await self._save_notify(ws, msg)
        elif kind == "family_hub/shared/save":
            linked = {p.get("ha_user_id") for p in self.config["persons"]}
            self.config["shared_users"] = [u for u in msg["users"] if u not in linked]
            # Like the integration's reload: the calendars carry the shared users.
            for state in self.states:
                if state["entity_id"].startswith(CALENDAR_PREFIX):
                    state["attributes"]["shared_users"] = list(self.config["shared_users"])
            await self._reply(
                ws, msg_id, True, {"saved": True, "users": self.config["shared_users"]}
            )
        elif kind in (
            "family_hub/ics/list",
            "family_hub/ics/add",
            "family_hub/ics/update",
            "family_hub/ics/refresh",
            "family_hub/ics/replace",
            "family_hub/ics/remove",
            "family_hub/ics/styles",
            "family_hub/ics/waste_types",
        ):
            await self._ics(ws, msg)
        elif kind == "lovelace/dashboards/list":
            listed = [{"url_path": p, "mode": "storage"} for p in self.dashboards if p]
            await self._reply(ws, msg_id, True, listed)
        elif kind == "lovelace/config":
            config = self.dashboards.get(msg.get("url_path"))
            if config is None:
                await self._reply(ws, msg_id, False, None, "No config found.", "config_not_found")
            else:
                await self._reply(ws, msg_id, True, copy.deepcopy(config))
        elif kind == "family_hub/notify/test":
            await self._notify_test(ws, msg)
        elif kind == "config/entity_registry/list":
            entries = [
                {"entity_id": e, "platform": "alexa_media", "name": e.split(".")[1].title()}
                for e in self.echos
            ]
            entries.append({"entity_id": "light.kitchen", "platform": "hue", "name": None})
            await self._reply(ws, msg_id, True, entries)
        elif kind == "get_states":
            await self._reply(ws, msg_id, True, copy.deepcopy(self.states))
        elif kind == "call_service":
            await self._call_service(ws, msg)
        else:
            await self._reply(ws, msg_id, False, None, "unknown command")

    async def _todo(self, data: dict[str, Any]) -> None:
        items = self.todo_items.setdefault(data["entity_id"], [])
        if self.calls[-1]["service"] == "add_item":
            items.append(
                {"uid": uuid.uuid4().hex[:8], "summary": data["item"], "status": "needs_action"}
            )
        elif self.calls[-1]["service"] == "update_item":
            for item in items:
                if item["uid"] == data["item"]:
                    item["status"] = data["status"]
        elif self.calls[-1]["service"] == "remove_item":
            items[:] = [i for i in items if i["uid"] not in data["item"]]

    async def _save_config(self, ws: web.WebSocketResponse, msg: dict[str, Any]) -> None:
        config = copy.deepcopy(msg["config"])
        if not config.get("family", {}).get("family_name"):
            await self._reply(ws, msg["id"], False, None, "family_name: required", "invalid_config")
            return
        # New categories get their id from the name, as the integration does.
        for category in config["categories"]:
            category.setdefault("id", category["name"].lower())
        for person in config["persons"]:
            person.setdefault("id", uuid.uuid4().hex[:8])
        self.config = {**config, "configured": True}
        self.saved_configs.append(copy.deepcopy(self.config))
        # Like the integration: calendars follow the categories, and persons go on each one.
        self.states = [s for s in self.states if not s["entity_id"].startswith(CALENDAR_PREFIX)]
        for category in config["categories"]:
            entity = f"calendar.family_hub_{category['name'].lower()}"
            self.states.append(
                {
                    "entity_id": entity,
                    "state": "off",
                    "attributes": {
                        "friendly_name": category["name"],
                        "category_name": category["name"],
                        "category_id": category["id"],
                        "persons": copy.deepcopy(config["persons"]),
                        "shared_users": list(config.get("shared_users", [])),
                    },
                }
            )
            self.events.setdefault(entity, [])
        await self._reply(ws, msg["id"], True, {"saved": True})

    async def _save_notify(self, ws: web.WebSocketResponse, msg: dict[str, Any]) -> None:
        """Like the integration: services must exist, and only the notification fields change."""
        self.notify_saves.append(copy.deepcopy(msg))
        persons = {p["id"]: p for p in self.config["persons"]}
        for person_id, changes in msg["persons"].items():
            if person_id not in persons:
                await self._reply(ws, msg["id"], False, None, "Unknown person", "not_found")
                return
            for key in ("phone_notify", "alexa_notify"):
                service = changes.get(key)
                if key == "phone_notify" and service and service not in self.notify_services:
                    await self._reply(ws, msg["id"], False, None, service, "unknown_service")
                    return
                if (
                    key == "alexa_notify"
                    and service not in (None, "", "all")
                    and service not in self.echos
                ):
                    await self._reply(ws, msg["id"], False, None, service, "unknown_service")
                    return
        for person_id, changes in msg["persons"].items():
            for key in (
                "phone_notify",
                "alexa_notify",
                "alexa_volume",
                "channels",
                "quiet_start",
                "quiet_end",
                "ha_user_id",
            ):
                if key in changes and changes[key] not in (None, ""):
                    persons[person_id][key] = changes[key]
                elif key in changes:
                    persons[person_id].pop(key, None)
        await self._reply(ws, msg["id"], True, {"saved": True})

    async def _ics(self, ws: web.WebSocketResponse, msg: dict[str, Any]) -> None:
        """Like the integration's external calendar commands, for the add-on's tests."""
        kind, msg_id = msg["type"], msg["id"]
        if kind == "family_hub/ics/list":
            calendars = [dict(v, id=k) for k, v in self.ics.items()]
            await self._reply(
                ws,
                msg_id,
                True,
                {
                    "calendars": copy.deepcopy(calendars),
                    "waste_styles": dict(self.waste_styles),
                    "waste_types": copy.deepcopy(self.waste_types),
                    "waste_kinds": {
                        t["id"]: {"label": t["label"], "icon": t["icon"]} for t in self.waste_types
                    },
                },
            )
            return
        if kind == "family_hub/ics/styles":
            self.waste_styles.update(msg["styles"])
            await self._reply(ws, msg_id, True, {"saved": True})
            return
        if kind == "family_hub/ics/waste_types":
            types = msg["types"]
            if not types or any(not t.get("label") for t in types):
                await self._reply(ws, msg_id, False, None, "types[0].label: 1 to 30", "bad_type")
                return
            self.waste_types = [
                {**t, "id": t.get("id") or t["label"].lower()} for t in copy.deepcopy(types)
            ]
            self.waste_styles = {t["id"]: t["color"] for t in self.waste_types}
            await self._reply(ws, msg_id, True, {"saved": True, "types": self.waste_types})
            return
        if kind == "family_hub/ics/add":
            content = msg.get("content")
            if content is not None and "BEGIN:VCALENDAR" not in content:
                await self._reply(ws, msg_id, False, None, "invalid", "invalid_ics")
                return
            source_id = uuid.uuid4().hex[:8]
            calendar = dict(msg["calendar"])
            self.ics[source_id] = {**calendar, "url": msg.get("url", ""), "content": content or ""}
            entity = f"calendar.family_hub_ext_{source_id}"
            self.states.append(
                {
                    "entity_id": entity,
                    "state": "off",
                    "attributes": {"friendly_name": calendar["name"]},
                }
            )
            self.events[entity] = [
                stored_event(calendar["name"], "2026-11-09T00:00:00", "2026-11-10T00:00:00")
            ]
            await self._reply(ws, msg_id, True, {"id": source_id})
            return
        source_id = str(msg["calendar_id"])
        if source_id not in self.ics:
            await self._reply(ws, msg_id, False, None, "Unknown calendar", "not_found")
            return
        if kind == "family_hub/ics/remove":
            del self.ics[source_id]
            self.states = [
                s for s in self.states if s["entity_id"] != f"calendar.family_hub_ext_{source_id}"
            ]
            await self._reply(ws, msg_id, True, {"removed": True})
        elif kind == "family_hub/ics/update":
            self.ics[source_id].update(msg["calendar"])
            await self._reply(ws, msg_id, True, {"saved": True})
        elif kind == "family_hub/ics/refresh":
            await self._reply(ws, msg_id, True, {"id": source_id, "error": None})
        else:
            self.ics[source_id]["content"] = msg["content"]
            await self._reply(ws, msg_id, True, {"saved": True})

    async def _notify_test(self, ws: web.WebSocketResponse, msg: dict[str, Any]) -> None:
        """Like the integration's test message: the person's chosen service only."""
        self.notify_tests.append(copy.deepcopy(msg))
        person = next((p for p in self.config["persons"] if p["id"] == msg["person"]), None)
        if person is None:
            await self._reply(ws, msg["id"], False, None, "Unknown person", "not_found")
            return
        if msg["kind"] == "phone":
            chosen = [person.get("phone_notify")] if person.get("phone_notify") else []
            chosen = [s for s in chosen if s in self.notify_services]
        else:
            choice = person.get("alexa_notify") or ""
            speakers = self.echos if choice == "all" else [choice]
            chosen = [s for s in speakers if s in self.echos] if choice else []
        if not chosen:
            await self._reply(ws, msg["id"], False, None, "No service chosen", "no_service")
            return
        self.calls.append({"domain": "notify", "service": msg["kind"], "data": {"to": chosen}})
        await self._reply(ws, msg["id"], True, {"sent": len(chosen)})

    async def _call_service(self, ws: web.WebSocketResponse, msg: dict[str, Any]) -> None:
        domain, service = msg["domain"], msg["service"]
        data = msg.get("service_data", {})
        if domain == "notify" and service not in self.notify_services:
            await self._reply(ws, msg["id"], False, None, "Service not found", "not_found")
            return
        self.calls.append({"domain": domain, "service": service, "data": data})
        if domain == DOMAIN and service == "add_event":
            entity = f"calendar.family_hub_{data['category']}"
            person_ids = ",".join(data.get("persons", []))
            shift_id = data.get("shift_id", "")
            self.events.setdefault(entity, []).append(
                stored_event(
                    data["summary"], data["start"], data.get("end", data["start"]), person_ids
                )
                | {"shift_id": shift_id, "notify": notify_text(data)}
            )
            await self.push_entity_change(entity)
        if domain == DOMAIN and service == "update_event":
            for events in self.events.values():
                for event in events:
                    if event["record_id"] == data["uid"]:
                        for key in ("summary", "start", "end"):
                            if key in data:
                                event[key] = data[key]
                        if "channels" in data:
                            event["notify"] = notify_text(data)
        if domain == "todo":
            await self._todo(data)
        if domain == DOMAIN and service == "delete_event":
            for events in self.events.values():
                events[:] = [e for e in events if e["record_id"] != data["uid"]]
            await self.push_entity_change(FAMILY)
        await self._reply(ws, msg["id"], True, {"context": {}, "response": None})

    async def _send_event(
        self, ws: web.WebSocketResponse, sub_id: int, event: dict[str, Any]
    ) -> None:
        await ws.send_json({"id": sub_id, "type": "event", "event": event})

    async def _reply(
        self,
        ws: web.WebSocketResponse,
        msg_id: int,
        success: bool,
        result: Any,
        error: str | None = None,
        code: str = "unknown_command",
    ) -> None:
        payload: dict[str, Any] = {"id": msg_id, "type": "result", "success": success}
        if success:
            payload["result"] = result
        else:
            payload["error"] = {"code": code, "message": error}
        await ws.send_json(payload)


DOMAIN = "family_hub"
CALENDAR_PREFIX = "calendar.family_hub_"
