"""Websocket commands of the "Condivisione" page: invites, devices, approvals, activity log.

All of them need a Home Assistant administrator. The tablet add-on (Supervisor token) calls them
only for adults of the family.
"""

from __future__ import annotations

from typing import Any

import probatio as vol  # Home Assistant's schema library (voluptuous successor).
from homeassistant.components.websocket_api import async_register_command
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.components.websocket_api.decorators import (
    async_response,
    require_admin,
    websocket_command,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import DOMAIN
from .guests import GuestError, GuestManager

GUEST_PATH = "/api/family_hub/guest/"


def _manager(hass: HomeAssistant, entry_id: str | None) -> GuestManager | None:
    entries = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if getattr(e, "runtime_data", None) is not None
    ]
    if entry_id is not None:
        entries = [e for e in entries if e.entry_id == entry_id]
    elif len(entries) != 1:
        return None
    if not entries:
        return None
    guests: GuestManager | None = entries[0].runtime_data.guests
    return guests


def base_url(hass: HomeAssistant) -> tuple[str, bool]:
    """The address the grandparents' phones use, and whether it works away from home (Nabu Casa
    or the family's own external address). Without one, the home address is given and the page
    warns that the link works only at home."""
    try:
        return get_url(hass, allow_internal=False, prefer_cloud=True), True
    except NoURLAvailableError:
        pass
    try:
        return get_url(hass, prefer_external=False), False
    except NoURLAvailableError:
        return "", False


def _error(connection: ActiveConnection, msg_id: int, err: GuestError) -> None:
    connection.send_error(msg_id, err.code, err.code)


def _not_set_up(connection: ActiveConnection, msg_id: int) -> None:
    connection.send_error(msg_id, "not_found", "Family Hub is not set up")


@require_admin
@websocket_command({vol.Required("type"): "family_hub/guest/list", vol.Optional("entry_id"): str})
@async_response
async def ws_list(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    manager = _manager(hass, msg.get("entry_id"))
    if manager is None:
        _not_set_up(connection, msg["id"])
        return
    url, external = base_url(hass)
    connection.send_result(
        msg["id"], {**manager.describe(), "external_url": external, "has_url": bool(url)}
    )


@require_admin
@websocket_command(
    {
        vol.Required("type"): "family_hub/guest/invite_create",
        vol.Optional("entry_id"): str,
        vol.Required("invite"): dict,
    }
)
@async_response
async def ws_invite_create(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """A new invite. The link (with its token after #) is in this answer only."""
    manager = _manager(hass, msg.get("entry_id"))
    if manager is None:
        _not_set_up(connection, msg["id"])
        return
    try:
        invite, token = await manager.async_create_invite(msg["invite"])
    except GuestError as err:
        _error(connection, msg["id"], err)
        return
    url, external = base_url(hass)
    connection.send_result(
        msg["id"],
        {
            "id": invite["id"],
            "link": f"{url.rstrip('/')}{GUEST_PATH}#i={token}",
            "external_url": external,
        },
    )


def _simple(command: str, schema: dict[Any, Any], action: Any) -> Any:
    """A command that runs one manager action and answers its result."""

    @require_admin
    @websocket_command(
        {
            vol.Required("type"): f"family_hub/guest/{command}",
            vol.Optional("entry_id"): str,
            **schema,
        }
    )
    @async_response
    async def handler(
        hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
    ) -> None:
        manager = _manager(hass, msg.get("entry_id"))
        if manager is None:
            _not_set_up(connection, msg["id"])
            return
        try:
            await action(manager, msg)
        except GuestError as err:
            _error(connection, msg["id"], err)
            return
        connection.send_result(msg["id"], manager.describe())

    return handler


async def _revoke(manager: GuestManager, msg: dict[str, Any]) -> None:
    await manager.async_revoke_invite(msg["invite_id"])


async def _confirm(manager: GuestManager, msg: dict[str, Any]) -> None:
    await manager.async_confirm(msg["device_id"], msg["accept"])


async def _update(manager: GuestManager, msg: dict[str, Any]) -> None:
    await manager.async_update_device(msg["device_id"], msg["changes"])


async def _disable(manager: GuestManager, msg: dict[str, Any]) -> None:
    await manager.async_disable(msg["device_id"])


async def _remove(manager: GuestManager, msg: dict[str, Any]) -> None:
    await manager.async_remove_device(msg["device_id"])


async def _approve(manager: GuestManager, msg: dict[str, Any]) -> None:
    await manager.async_approve(msg["pending_id"], msg["accept"], msg.get("changes"))


COMMANDS = [
    _simple("invite_revoke", {vol.Required("invite_id"): str}, _revoke),
    _simple(
        "device_confirm", {vol.Required("device_id"): str, vol.Required("accept"): bool}, _confirm
    ),
    _simple(
        "device_update", {vol.Required("device_id"): str, vol.Required("changes"): dict}, _update
    ),
    _simple("device_disable", {vol.Required("device_id"): str}, _disable),
    _simple("device_remove", {vol.Required("device_id"): str}, _remove),
    _simple(
        "pending_decide",
        {
            vol.Required("pending_id"): str,
            vol.Required("accept"): bool,
            vol.Optional("changes"): dict,
        },
        _approve,
    ),
]


@callback
def async_register_guest_commands(hass: HomeAssistant) -> None:
    async_register_command(hass, ws_list)
    async_register_command(hass, ws_invite_create)
    for command in COMMANDS:
        async_register_command(hass, command)
