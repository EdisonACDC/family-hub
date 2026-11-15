"""Invites, 0.9.0b6: who gets the requests (phones, admin fallback), cleaning up invites and
devices, and "Nuovo telefono". Names are invented."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from aiohttp.test_utils import TestClient
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_guests import (  # noqa: F401 - the fixtures are used by name
    API,
    GRANDMA,
    _activate,
    _auth,
    _device,
    _invite,
    _list,
    _manager,
    _new,
    _unlimited,
    _ws,
    client,
    family,
    fresh_limits,
    no_real_push,
)

# ----- who gets the requests ---------------------------------------------------------


async def test_requests_go_to_admins_with_the_app_when_no_adult_has_a_phone(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    hass_admin_user: Any,
    hass_read_only_user: Any,
) -> None:
    """Mamma's phone service does not exist here: the requests go to the administrators who
    have the Companion app (not to other users), with Conferma / Rifiuta, and open Family Hub."""
    admin_calls: list[Any] = []
    user_calls: list[Any] = []
    for user, name, calls in (
        (hass_admin_user, "Telefono Prova Admin", admin_calls),
        (hass_read_only_user, "Telefono Prova Utente", user_calls),
    ):
        MockConfigEntry(
            domain="mobile_app", data={"user_id": user.id, "device_name": name}
        ).add_to_hass(hass)
        hass.services.async_register("notify", slugify(f"mobile_app_{name}"), calls.append)
    answer = await _ws(hass, hass_ws_client, "panel", path="/app/abcd1234_family_hub_ui")
    assert answer["success"]
    _, invite_token = await _invite(hass, hass_ws_client)
    await _activate(client, invite_token)
    await hass.async_block_till_done()
    assert user_calls == []
    (call,) = admin_calls
    data = call.data["data"]
    assert [a["title"] for a in data["actions"]] == ["Conferma", "Rifiuta"]
    device_id = (await _ws(hass, hass_ws_client, "list"))["result"]["devices"][0]["id"]
    expected = f"/app/abcd1234_family_hub_ui?fh_open=device.{device_id}"
    assert data["url"] == data["clickAction"] == expected
    assert data["tag"] == f"family_hub_guest_{device_id}"
    listed = (await _ws(hass, hass_ws_client, "list"))["result"]
    assert listed["attention"] == "devices"
    # The button on the admin's phone confirms the phone.
    action = data["actions"][0]["action"]
    hass.bus.async_fire("mobile_app_notification_action", {"action": action})
    await hass.async_block_till_done()
    listed = (await _ws(hass, hass_ws_client, "list"))["result"]
    assert listed["devices"][0]["status"] == "active"
    assert listed["attention"] == ""


async def test_the_panel_address_is_checked(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
) -> None:
    for bad in ("app/x", "https://evil.example/app", "/app/x?y=1", "/" + "a" * 90):
        assert not (await _ws(hass, hass_ws_client, "panel", path=bad))["success"]


async def test_requests_go_to_the_chosen_persons(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    calls: list[Any] = []
    hass.services.async_register("notify", "mobile_app_telefono_mamma", calls.append)
    for bad in (
        {"mode": "tutti"},
        {"mode": "persons", "persons": []},
        {"mode": "persons", "persons": ["nessuno"]},
    ):
        assert not (await _ws(hass, hass_ws_client, "recipients_save", recipients=bad))["success"]
    answer = await _ws(
        hass,
        hass_ws_client,
        "recipients_save",
        recipients={"mode": "persons", "persons": ["mamma"]},
    )
    assert answer["result"]["recipients"] == {
        "mode": "persons",
        "persons": ["mamma"],
        "shifts": True,
    }
    _, token = await _device(hass, client, hass_ws_client)
    calls.clear()
    await client.post(f"{API}events", json=_new(), headers=_auth(token))
    await hass.async_block_till_done()
    (call,) = calls
    assert [a["title"] for a in call.data["data"]["actions"]] == ["Approva", "Rifiuta"]
    assert (await _ws(hass, hass_ws_client, "list"))["result"]["attention"] == "approvals"


# ----- cleaning up invites and devices ----------------------------------------------------


async def test_closed_invites_can_be_deleted_and_go_after_30_days(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    manager = _manager(family)
    open_id, _ = await _invite(hass, hass_ws_client, name="Aperto")
    used_id, used = await _invite(hass, hass_ws_client, name="Usato")
    revoked_id, _ = await _invite(hass, hass_ws_client, name="Annullato")
    expired_id, _ = await _invite(hass, hass_ws_client, name="Scaduto")
    old_id, _ = await _invite(hass, hass_ws_client, name="Vecchio")
    await _activate(client, used)
    await _ws(hass, hass_ws_client, "invite_revoke", invite_id=revoked_id)
    manager.invites[expired_id]["expires_at"] = (dt_util.utcnow() - timedelta(days=1)).isoformat()
    # An open invite cannot be deleted.
    answer = await _ws(hass, hass_ws_client, "invite_delete", invite_id=open_id)
    assert not answer["success"] and answer["error"]["code"] == "still_open"
    assert (await _ws(hass, hass_ws_client, "invite_delete", invite_id=revoked_id))["success"]
    # Closed more than 30 days ago: gone by itself; the log keeps what happened.
    await _ws(hass, hass_ws_client, "invite_revoke", invite_id=old_id)
    manager.invites[old_id]["closed_at"] = (dt_util.utcnow() - timedelta(days=31)).isoformat()
    log_before = len(manager.log)
    assert manager._cleanup_invites()
    assert old_id not in manager.invites and len(manager.log) == log_before
    # Closed less than 30 days ago: kept.
    assert used_id in manager.invites and expired_id in manager.invites
    # "Elimina tutti quelli non attivi": only the open one stays.
    listed = (await _ws(hass, hass_ws_client, "invite_cleanup"))["result"]
    # The open one stays, and so does the one a phone is using (here: waiting for an adult).
    assert sorted(i["id"] for i in listed["invites"]) == sorted([open_id, used_id])
    assert expired_id not in manager.invites


async def test_an_invite_in_use_by_an_active_phone_is_never_deleted(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    manager = _manager(family)
    await _invite(hass, hass_ws_client, name="Zia")  # keeps the web app on
    device_id, _ = await _device(hass, client, hass_ws_client)
    invite_id = manager.devices[device_id]["invite_id"]
    listed = (await _ws(hass, hass_ws_client, "list"))["result"]
    shown = next(i for i in listed["invites"] if i["id"] == invite_id)
    assert shown["status"] == "used" and shown["in_use"] is True
    answer = await _ws(hass, hass_ws_client, "invite_delete", invite_id=invite_id)
    assert not answer["success"] and answer["error"]["code"] == "in_use"
    await _ws(hass, hass_ws_client, "invite_cleanup")
    assert invite_id in manager.invites
    # Not even after 30 days.
    manager.invites[invite_id]["closed_at"] = (dt_util.utcnow() - timedelta(days=60)).isoformat()
    assert not manager._cleanup_invites()
    assert invite_id in manager.invites
    # "Nuovo telefono" finds the permissions to copy.
    result = (await _ws(hass, hass_ws_client, "device_replace", device_id=device_id))["result"]
    assert manager.invites[result["id"]]["persons"] == manager.devices[device_id]["persons"]
    # Once the phone is off, its invite can go.
    listed = (await _ws(hass, hass_ws_client, "list"))["result"]
    assert next(i for i in listed["invites"] if i["id"] == invite_id)["in_use"] is False
    assert (await _ws(hass, hass_ws_client, "invite_delete", invite_id=invite_id))["success"]


async def test_deleting_a_device_deletes_its_used_invite(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    await _invite(hass, hass_ws_client, name="Zia")  # keeps the web app on
    device_id, _ = await _device(hass, client, hass_ws_client)
    invite_id = _manager(family).devices[device_id]["invite_id"]
    await _ws(hass, hass_ws_client, "device_disable", device_id=device_id)
    assert (await _ws(hass, hass_ws_client, "device_remove", device_id=device_id))["success"]
    assert invite_id not in _manager(family).invites
    assert device_id not in _manager(family).devices


# ----- "Nuovo telefono" ------------------------------------------------------------------


async def test_a_new_phone_takes_the_place_of_the_old_one(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    manager = _manager(family)
    old_id, old_token = await _device(
        hass, client, hass_ws_client, approval="direct", permission="edit_own"
    )
    _unlimited(hass)
    answer = await client.post(f"{API}events", json=_new(), headers=_auth(old_token))
    uid = (await answer.json())["event"]["id"]
    old_invite = manager.devices[old_id]["invite_id"]
    answer = await _ws(hass, hass_ws_client, "device_replace", device_id=old_id)
    assert answer["success"]
    result = answer["result"]
    assert "#i=" in result["link"]
    # The old phone is off at once.
    assert (await _list(client, old_token)).status == 403
    new_invite = manager.invites[result["id"]]
    assert new_invite["name"] == GRANDMA and new_invite["replaces"] == old_id
    for key in ("persons", "categories", "permission", "approval", "notify"):
        assert new_invite[key] == manager.devices[old_id][key]
    activated = await _activate(client, result["link"].split("#i=")[1])
    new_token = (await activated.json())["token"]
    (new_id,) = [d for d in manager.devices if d != old_id]
    await _ws(hass, hass_ws_client, "device_confirm", device_id=new_id, accept=True)
    # One phone with that name; the old one and its invite are gone.
    listed = (await _ws(hass, hass_ws_client, "list"))["result"]
    assert [(d["name"], d["status"]) for d in listed["devices"]] == [(GRANDMA, "active")]
    assert old_id not in manager.devices and old_invite not in manager.invites
    # The appointment "aggiunto da" stays linked: the new phone may change it.
    assert family.runtime_data.store.events[uid]["added_by"]["device"] == new_id
    changed = await client.put(
        f"{API}events/{uid}", json=_new(title="Merenda cambiata"), headers=_auth(new_token)
    )
    assert changed.status == 200
    assert any(e["kind"] == "replaced" and e["name"] == GRANDMA for e in listed["log"])


async def test_a_rejected_new_phone_leaves_the_old_one_off(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    manager = _manager(family)
    old_id, _ = await _device(hass, client, hass_ws_client)
    result = (await _ws(hass, hass_ws_client, "device_replace", device_id=old_id))["result"]
    await _activate(client, result["link"].split("#i=")[1])
    (new_id,) = [d for d in manager.devices if d != old_id]
    await _ws(hass, hass_ws_client, "device_confirm", device_id=new_id, accept=False)
    assert manager.devices[old_id]["status"] == "disabled"
    assert manager.devices[new_id]["status"] == "rejected"
