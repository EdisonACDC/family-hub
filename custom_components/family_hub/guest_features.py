"""What each guest may use in the web app: mode, template and features (Family Hub 0.10).

An adult chooses, for every invite and every phone and only from Home Assistant, what the guest
may see and do. By default only the calendar, read only. Every request is checked on the server
(guests.py); hiding a part of the web app is never the only protection.

* mode: "simple" (big letters, few items, for the grandparents) or "full" (like the panel).
* template: the ready-made choice the adult started from ("grandparents", "babysitter",
  "relative" or "custom"). Only a label: every field stays editable by hand.
* features: calendar, reminders, lists, waste (rubbish days), weather.
* lists: the family's to-do lists the guest may open (none by default), and whether it may add
  and tick items.

Never for a guest: sharing and invites, the guide, Family Hub's or Home Assistant's settings,
device management. The web app has no address for any of them.

Invites and phones made before 0.10 have none of these fields: they become "grandparents" with
the permissions they have today (see ``upgrade``).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

LOGGER = logging.getLogger(__name__)

MODE_SIMPLE = "simple"
MODE_FULL = "full"
MODES = (MODE_SIMPLE, MODE_FULL)

CALENDAR = "calendar"
REMINDERS = "reminders"
LISTS = "lists"
WASTE = "waste"
WEATHER = "weather"
FEATURES = (CALENDAR, REMINDERS, LISTS, WASTE, WEATHER)

GRANDPARENTS = "grandparents"
BABYSITTER = "babysitter"
RELATIVE = "relative"
CUSTOM = "custom"
TEMPLATES = (GRANDPARENTS, BABYSITTER, RELATIVE, CUSTOM)

# The fields of an invite or a device that this module adds.
KEYS = ("mode", "template", "features", "lists", "lists_edit")

MAX_LISTS = 20
MAX_ITEM = 100
MAX_ITEMS = 300


def _features(**on: bool) -> dict[str, bool]:
    return {name: bool(on.get(name, False)) for name in FEATURES}


def base_scope() -> dict[str, Any]:
    """Everything off but the calendar, read only."""
    return {
        "mode": MODE_SIMPLE,
        "template": CUSTOM,
        "features": _features(calendar=True),
        "permission": "view",
        "approval": "approve",
        "notify": False,
        "family_events": False,
        "has_shifts": False,
        "lists": [],
        "lists_edit": False,
    }


# What each template turns on. The adult can change all of it afterwards.
PRESETS: dict[str, dict[str, Any]] = {
    # Simple; the chosen children's calendar; may add appointments; their own work shifts.
    GRANDPARENTS: {
        "mode": MODE_SIMPLE,
        "permission": "add",
        "approval": "approve",
        "has_shifts": True,
        "features": _features(calendar=True),
    },
    # Simple; the chosen children's calendar, read only; no lists.
    BABYSITTER: {
        "mode": MODE_SIMPLE,
        "permission": "view",
        "features": _features(calendar=True),
    },
    # Full; the functions the adult chooses (a starting set).
    RELATIVE: {
        "mode": MODE_FULL,
        "permission": "edit_own",
        "approval": "direct",
        "notify": True,
        "features": _features(calendar=True, reminders=True, waste=True, weather=True),
    },
}


def defaults_for(raw: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """The values used for the fields ``raw`` leaves out, and whether ``raw`` is a request of
    before 0.10 (no template, no mode, no features): those keep the old defaults, so a 0.9
    client gets what it got before."""
    template = raw.get("template")
    if template in PRESETS:
        return {**base_scope(), **PRESETS[template], "template": template}, False
    if template is not None or "features" in raw or "mode" in raw:
        return base_scope(), False
    legacy = {**base_scope(), "template": GRANDPARENTS, "notify": True}
    return legacy, True


def clean(raw: dict[str, Any], known_lists: list[str]) -> dict[str, Any] | None:
    """Mode, template, features and lists, checked; None for a value that is not allowed."""
    defaults, legacy = defaults_for(raw)
    mode = raw.get("mode", defaults["mode"])
    template = raw.get("template", defaults["template"])
    if mode not in MODES or template not in TEMPLATES:
        return None
    features = dict(defaults["features"])
    given = raw.get("features")
    if given is not None:
        if not isinstance(given, dict) or not set(given) <= set(FEATURES):
            return None
        if not all(isinstance(v, bool) for v in given.values()):
            return None
        features.update(given)
    elif legacy:
        # Before 0.10 the reminders came with the notifications.
        features[REMINDERS] = bool(raw.get("notify", True))
    lists = raw.get("lists", defaults["lists"])
    lists_edit = raw.get("lists_edit", defaults["lists_edit"])
    if (
        not isinstance(lists, list)
        or len(lists) > MAX_LISTS
        or not all(isinstance(e, str) and e in known_lists for e in lists)
        or not isinstance(lists_edit, bool)
    ):
        return None
    return {
        "mode": mode,
        "template": template,
        "features": features,
        "lists": list(dict.fromkeys(lists)),
        "lists_edit": lists_edit,
    }


def upgrade(item: dict[str, Any]) -> bool:
    """An invite or a phone of 0.9: the "grandparents" template with the permissions it has
    today (reminders with its notifications, nothing new). True if it changed."""
    if isinstance(item.get("features"), dict):
        return False
    item["mode"] = MODE_SIMPLE
    item["template"] = GRANDPARENTS
    item["features"] = _features(calendar=True, reminders=bool(item.get("notify", True)))
    item["lists"] = []
    item["lists_edit"] = False
    return True


def has(item: dict[str, Any], feature: str) -> bool:
    features = item.get("features")
    if not isinstance(features, dict):
        return feature == CALENDAR
    return bool(features.get(feature, False))


def describe(item: dict[str, Any]) -> dict[str, Any]:
    """The fields the "Condivisione" page shows and edits."""
    return {
        "mode": item.get("mode") or MODE_SIMPLE,
        "template": item.get("template") or CUSTOM,
        "features": {name: has(item, name) for name in FEATURES},
        "lists": list(item.get("lists") or []),
        "lists_edit": bool(item.get("lists_edit", False)),
    }


# ----- the family's to-do lists ------------------------------------------------------------


def family_lists(options: Any) -> list[str]:
    """The to-do lists the guide chose for Family Hub: the only ones an adult may give a guest."""
    sources = options.get("sources") if hasattr(options, "get") else None
    todo = sources.get("todo") if isinstance(sources, dict) else None
    return [str(e) for e in todo or [] if isinstance(e, str) and e.startswith("todo.")]


def list_id(entry_id: str, entity_id: str) -> str:
    """The name of a list in the web app: never the entity id of Home Assistant."""
    return hashlib.sha256(f"{entry_id}:{entity_id}".encode()).hexdigest()[:16]


def list_name(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    name = state.attributes.get("friendly_name") if state is not None else None
    return str(name or entity_id.split(".", 1)[-1].replace("_", " ").capitalize())


async def list_items(hass: HomeAssistant, entity_id: str) -> list[dict[str, Any]]:
    """The items of one list: only id, text and done."""
    try:
        result: Any = await hass.services.async_call(
            "todo",
            "get_items",
            {"entity_id": entity_id},
            blocking=True,
            return_response=True,
        )
    except HomeAssistantError as err:
        LOGGER.debug("List %s not readable: %s", entity_id, err)
        return []
    items = (result or {}).get(entity_id, {}).get("items", [])
    return [
        {
            "id": str(item.get("uid") or ""),
            "summary": str(item.get("summary") or "")[:MAX_ITEM],
            "done": item.get("status") == "completed",
        }
        for item in items[:MAX_ITEMS]
        if isinstance(item, dict) and item.get("uid")
    ]


async def add_item(hass: HomeAssistant, entity_id: str, summary: str) -> None:
    await hass.services.async_call(
        "todo", "add_item", {"entity_id": entity_id, "item": summary}, blocking=True
    )


async def set_done(hass: HomeAssistant, entity_id: str, uid: str, done: bool) -> None:
    await hass.services.async_call(
        "todo",
        "update_item",
        {"entity_id": entity_id, "item": uid, "status": "completed" if done else "needs_action"},
        blocking=True,
    )
