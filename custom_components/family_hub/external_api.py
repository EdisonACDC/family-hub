"""Websocket commands for external calendars. All need a Home Assistant administrator; the
add-on checks that only adults use them.

A link is stored with its address (shown to adults only, by the add-on). A file is stored as
text in Home Assistant's storage. Every command validates first; nothing is written when a
check fails.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import probatio as vol  # Home Assistant's schema library (voluptuous successor).
from homeassistant.components.websocket_api import async_register_command
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.components.websocket_api.decorators import (
    async_response,
    require_admin,
    websocket_command,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN, OPT_PERSONS
from .external import (
    OPT_EXTERNAL,
    OPT_WASTE_STYLE,
    TYPES,
    ExternalError,
    check_url,
    download,
    parse,
)
from .waste import OPT_WASTE_TYPES, WasteTypeError, clean_types  # noqa: E402

FIELDS = ("name", "type", "color", "icon", "remind_at", "morning_at", "return_notice")


def _entry(hass: HomeAssistant, entry_id: str | None) -> ConfigEntry | None:
    entries = hass.config_entries.async_entries(DOMAIN)
    if entry_id is not None:
        return next((e for e in entries if e.entry_id == entry_id), None)
    return entries[0] if len(entries) == 1 else None


def _text(value: Any, field: str, max_len: int, required: bool = False) -> str:
    text = "" if value is None else str(value).strip()
    if required and not text:
        raise ExternalError(f"{field}_required")
    if len(text) > max_len:
        raise ExternalError(f"{field}_too_long")
    return text


def _clean(
    raw: dict[str, Any], persons: set[str], current: dict[str, Any] | None
) -> dict[str, Any]:
    """Validate the fields of one external calendar. Missing fields keep their current value."""
    base = dict(current or {})
    if "name" in raw or current is None:
        base["name"] = _text(raw.get("name"), "name", 60, required=True)
    if "type" in raw or current is None:
        kind = raw.get("type", "altro")
        if kind not in TYPES:
            raise ExternalError("bad_type")
        base["type"] = kind
    if "color" in raw or current is None:
        color = str(raw.get("color", "#64748B"))
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
            raise ExternalError("bad_color")
        base["color"] = color
    if "icon" in raw or current is None:
        base["icon"] = _text(raw.get("icon", "calendar"), "icon", 30) or "calendar"
    if "persons" in raw or current is None:
        chosen = raw.get("persons", [])
        if not isinstance(chosen, list) or not all(
            isinstance(p, str) and p in persons for p in chosen
        ):
            raise ExternalError("bad_person")
        base["persons"] = list(dict.fromkeys(chosen))
    for key in ("remind_at", "morning_at"):
        if key in raw:
            value = str(raw[key] or "")
            if value and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
                raise ExternalError("bad_time")
            base[key] = value
    if "return_notice" in raw:
        base["return_notice"] = bool(raw["return_notice"])
    return base


async def _manager(hass: HomeAssistant, entry_id: str | None) -> tuple[ConfigEntry, Any] | None:
    entry = _entry(hass, entry_id)
    if entry is None or entry.runtime_data is None or entry.runtime_data.external is None:
        return None
    return entry, entry.runtime_data.external


def _status_of(manager: Any, source: dict[str, Any]) -> dict[str, Any]:
    status = manager.status(source["id"])
    return {
        "id": source["id"],
        "name": source["name"],
        "type": source["type"],
        "color": source["color"],
        "icon": source["icon"],
        "persons": list(source.get("persons", [])),
        "remind_at": source.get("remind_at", ""),
        "morning_at": source.get("morning_at", ""),
        "return_notice": bool(source.get("return_notice", False)),
        "source": ("manual" if source.get("manual") else ("link" if source.get("url") else "file")),
        "url": source.get("url", ""),
        "updated": status.get("updated"),
        "error": status.get("error"),
    }


@require_admin
@websocket_command({vol.Required("type"): "family_hub/ics/list", vol.Optional("entry_id"): str})
@async_response
async def ws_ics_list(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    found = await _manager(hass, msg.get("entry_id"))
    if found is None:
        connection.send_error(msg["id"], "not_found", "Family Hub is not set up")
        return
    entry, manager = found
    connection.send_result(
        msg["id"],
        {
            # The files and links, and the pickups made by hand (sources() has both).
            "calendars": [_status_of(manager, s) for s in manager.sources()],
            "waste_styles": manager.waste_styles(),
            "waste_types": manager.waste_types(),
            "waste_kinds": {
                k["id"]: {"label": k["label"], "icon": k["icon"]} for k in manager.waste_types()
            },
        },
    )


@require_admin
@websocket_command(
    {
        vol.Required("type"): "family_hub/ics/styles",
        vol.Optional("entry_id"): str,
        vol.Required("styles"): dict,
    }
)
@async_response
async def ws_ics_styles(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Colour of each rubbish type (the others keep theirs)."""
    found = await _manager(hass, msg.get("entry_id"))
    if found is None:
        connection.send_error(msg["id"], "not_found", "Family Hub is not set up")
        return
    entry, manager = found
    types = manager.waste_types()
    known = {kind["id"]: kind for kind in types}
    chosen = dict(entry.options.get(OPT_WASTE_STYLE, {}))
    for kind_id, color in msg["styles"].items():
        if kind_id not in known:
            connection.send_error(msg["id"], "bad_type", "Unknown rubbish kind")
            return
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
            connection.send_error(msg["id"], "bad_color", "Invalid colour")
            return
        known[kind_id]["color"] = color.upper()
        chosen[kind_id] = color
    options = {**entry.options, OPT_WASTE_STYLE: chosen}
    if OPT_WASTE_TYPES in entry.options:
        options[OPT_WASTE_TYPES] = types
    hass.config_entries.async_update_entry(entry, options=options)
    connection.send_result(msg["id"], {"saved": True})


@require_admin
@websocket_command(
    {
        vol.Required("type"): "family_hub/ics/waste_types",
        vol.Optional("entry_id"): str,
        vol.Required("types"): list,
    }
)
@async_response
async def ws_ics_waste_types(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """The whole list of rubbish types: label, icon, text to look for, colour."""
    entry = _entry(hass, msg.get("entry_id"))
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Family Hub is not set up")
        return
    try:
        types = clean_types(msg["types"])
    except WasteTypeError as err:
        connection.send_error(msg["id"], "bad_type", str(err))
        return
    hass.config_entries.async_update_entry(entry, options={**entry.options, OPT_WASTE_TYPES: types})
    connection.send_result(msg["id"], {"saved": True, "types": types})


@require_admin
@websocket_command(
    {
        vol.Required("type"): "family_hub/ics/add",
        vol.Optional("entry_id"): str,
        vol.Required("calendar"): dict,
        vol.Optional("url"): str,
        vol.Optional("content"): str,
    }
)
@async_response
async def ws_ics_add(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Add a calendar from a link or from file content. Nothing is kept if it is not valid."""
    found = await _manager(hass, msg.get("entry_id"))
    if found is None:
        connection.send_error(msg["id"], "not_found", "Family Hub is not set up")
        return
    entry, manager = found
    persons = {p["id"] for p in entry.options.get(OPT_PERSONS, [])}
    try:
        source = _clean(msg["calendar"], persons, None)
        source_id = uuid.uuid4().hex[:8]
        if msg.get("url"):
            url = check_url(str(msg["url"]))
            text = await download(hass, url)
            parse(text)
            source["url"] = url
        elif msg.get("content"):
            text = str(msg["content"])
            parse(text)
        else:
            raise ExternalError("no_source")
    except ExternalError as err:
        connection.send_error(msg["id"], err.code, err.code)
        return
    source["id"] = source_id
    manager.data["contents"][source_id] = text
    manager.data["status"][source_id] = {"updated": dt_util.now().isoformat(), "error": None}
    # The content is stored before the options: the reload that follows reads it.
    await manager.async_save()
    hass.config_entries.async_update_entry(
        entry,
        options={**entry.options, OPT_EXTERNAL: [*entry.options.get(OPT_EXTERNAL, []), source]},
    )
    connection.send_result(msg["id"], {"id": source_id})


@require_admin
@websocket_command(
    {
        vol.Required("type"): "family_hub/ics/update",
        vol.Optional("entry_id"): str,
        vol.Required("calendar_id"): str,
        vol.Required("calendar"): dict,
    }
)
@async_response
async def ws_ics_update(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    entry = _entry(hass, msg.get("entry_id"))
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Family Hub is not set up")
        return
    sources = list(entry.options.get(OPT_EXTERNAL, []))
    current = next((s for s in sources if s["id"] == msg["calendar_id"]), None)
    if current is None:
        connection.send_error(msg["id"], "not_found", "Unknown calendar")
        return
    persons = {p["id"] for p in entry.options.get(OPT_PERSONS, [])}
    try:
        cleaned = _clean(msg["calendar"], persons, current)
    except ExternalError as err:
        connection.send_error(msg["id"], err.code, err.code)
        return
    updated = [cleaned if s["id"] == msg["calendar_id"] else s for s in sources]
    hass.config_entries.async_update_entry(entry, options={**entry.options, OPT_EXTERNAL: updated})
    connection.send_result(msg["id"], {"saved": True})


@require_admin
@websocket_command(
    {
        vol.Required("type"): "family_hub/ics/refresh",
        vol.Optional("entry_id"): str,
        vol.Required("calendar_id"): str,
    }
)
@async_response
async def ws_ics_refresh(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Download a link again now. A failure keeps the last valid copy and reports the error."""
    found = await _manager(hass, msg.get("entry_id"))
    if found is None:
        connection.send_error(msg["id"], "not_found", "Family Hub is not set up")
        return
    entry, manager = found
    source = next(
        (s for s in entry.options.get(OPT_EXTERNAL, []) if s["id"] == msg["calendar_id"]), None
    )
    if source is None:
        connection.send_error(msg["id"], "not_found", "Unknown calendar")
        return
    if not source.get("url"):
        connection.send_error(msg["id"], "not_a_link", "This calendar comes from a file")
        return
    await manager.async_refresh(msg["calendar_id"])
    connection.send_result(msg["id"], _status_of(manager, source))


@require_admin
@websocket_command(
    {
        vol.Required("type"): "family_hub/ics/replace",
        vol.Optional("entry_id"): str,
        vol.Required("calendar_id"): str,
        vol.Required("content"): str,
    }
)
@async_response
async def ws_ics_replace(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    found = await _manager(hass, msg.get("entry_id"))
    if found is None:
        connection.send_error(msg["id"], "not_found", "Family Hub is not set up")
        return
    entry, manager = found
    source = next(
        (s for s in entry.options.get(OPT_EXTERNAL, []) if s["id"] == msg["calendar_id"]), None
    )
    if source is None:
        connection.send_error(msg["id"], "not_found", "Unknown calendar")
        return
    try:
        await manager.async_set_content(msg["calendar_id"], str(msg["content"]))
    except ExternalError as err:
        connection.send_error(msg["id"], err.code, err.code)
        return
    connection.send_result(msg["id"], {"saved": True})


@require_admin
@websocket_command(
    {
        vol.Required("type"): "family_hub/ics/remove",
        vol.Optional("entry_id"): str,
        vol.Required("calendar_id"): str,
    }
)
@async_response
async def ws_ics_remove(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    found = await _manager(hass, msg.get("entry_id"))
    if found is None:
        connection.send_error(msg["id"], "not_found", "Family Hub is not set up")
        return
    entry, manager = found
    kept = [s for s in entry.options.get(OPT_EXTERNAL, []) if s["id"] != msg["calendar_id"]]
    if len(kept) == len(entry.options.get(OPT_EXTERNAL, [])):
        connection.send_error(msg["id"], "not_found", "Unknown calendar")
        return
    await manager.async_forget(msg["calendar_id"])
    hass.config_entries.async_update_entry(entry, options={**entry.options, OPT_EXTERNAL: kept})
    connection.send_result(msg["id"], {"removed": True})


def async_register_external_commands(hass: HomeAssistant) -> None:
    for command in (
        ws_ics_list,
        ws_ics_add,
        ws_ics_update,
        ws_ics_refresh,
        ws_ics_replace,
        ws_ics_remove,
        ws_ics_styles,
        ws_ics_waste_types,
    ):
        async_register_command(hass, command)
