"""Family Hub 0.10: what each guest may use is chosen per guest, from Home Assistant only, and
checked on the server. Default: only the calendar, read only. Templates "Nonni", "Babysitter",
"Familiare"; modes Semplice / Completa; lists, rubbish days, weather, reminders. Invites and phones
of 0.9 become "Nonni" with the permissions they have. Names are invented."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.family_hub import guest_features as gf
from custom_components.family_hub import webpush
from custom_components.family_hub.const import (
    CONF_FAMILY_NAME,
    CONF_LANGUAGE,
    DOMAIN,
    OPT_CATEGORIES,
    OPT_PERSONS,
)
from custom_components.family_hub.guests import RateLimiter, guest_hub, token_hash

API = "/api/family_hub/guest/api/"
SUBSCRIPTION = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/abc123",
    "keys": {"p256dh": "B" + "A" * 86, "auth": "c2VjcmV0YXV0aDEyMzQ"},
}
PERSONS = [
    {"id": "sofia", "name": "Sofia", "color": "#FF8800", "role": "child"},
    {"id": "mamma", "name": "Mamma Riservata", "color": "#123456", "role": "adult"},
]
CATEGORIES = [{"id": "scuola", "name": "Scuola", "color": "#22C55E"}]
LISTS = ["todo.spesa_esempio", "todo.lavori_adulti"]
WEATHER = "weather.casa_esempio"


@pytest.fixture
async def family(hass: HomeAssistant) -> MockConfigEntry:
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it"},
        options={
            OPT_PERSONS: PERSONS,
            OPT_CATEGORIES: CATEGORIES,
            CONF_LANGUAGE: "it",
            "sources": {"todo": LISTS, "calendars": [], "weather": [WEATHER]},
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.fixture
async def client(
    hass: HomeAssistant, family: MockConfigEntry, hass_client_no_auth: Any
) -> AsyncIterator[TestClient]:
    hub = guest_hub(hass)
    hub.read_limit = RateLimiter(10_000)
    hub.write_limit = RateLimiter(10_000)
    yield await hass_client_no_auth()


@pytest.fixture
def todo(hass: HomeAssistant) -> dict[str, list[dict[str, str]]]:
    """Two to-do lists of the family, as Home Assistant's todo services answer them."""
    lists: dict[str, list[dict[str, str]]] = {
        LISTS[0]: [{"uid": "u1", "summary": "Latte", "status": "needs_action"}],
        LISTS[1]: [{"uid": "u9", "summary": "SEGRETO-ADULTI", "status": "needs_action"}],
    }

    async def get_items(call: ServiceCall) -> dict[str, Any]:
        ids = call.data["entity_id"]
        ids = ids if isinstance(ids, list) else [ids]
        return {e: {"items": lists[e]} for e in ids}

    async def add_item(call: ServiceCall) -> None:
        entity = call.data["entity_id"]
        entity = entity[0] if isinstance(entity, list) else entity
        lists[entity].append(
            {
                "uid": f"n{len(lists[entity])}",
                "summary": call.data["item"],
                "status": "needs_action",
            }
        )

    async def update_item(call: ServiceCall) -> None:
        entity = call.data["entity_id"]
        entity = entity[0] if isinstance(entity, list) else entity
        for item in lists[entity]:
            if item["uid"] == call.data["item"]:
                item["status"] = call.data["status"]

    hass.services.async_register(
        "todo", "get_items", get_items, supports_response=SupportsResponse.ONLY
    )
    hass.services.async_register("todo", "add_item", add_item)
    hass.services.async_register("todo", "update_item", update_item)
    hass.states.async_set(LISTS[0], "1", {"friendly_name": "Spesa"})
    hass.states.async_set(LISTS[1], "1", {"friendly_name": "Lavori adulti"})
    return lists


async def _ws(ws_client: Any, command: str, **data: Any) -> dict[str, Any]:
    client = await ws_client()
    await client.send_json_auto_id({"type": f"family_hub/guest/{command}", **data})
    return await client.receive_json()


async def _phone(client: TestClient, ws_client: Any, **invite: Any) -> tuple[str, dict[str, str]]:
    """An invite with these choices, opened and confirmed: the device id and its headers."""
    created = await _ws(
        ws_client,
        "invite_create",
        invite={"name": "Nonna Prova", "persons": ["sofia"], "categories": ["scuola"], **invite},
    )
    assert created["success"], created
    token = created["result"]["link"].split("#i=")[1]
    answer = await client.post(f"{API}activate", json={"token": token})
    device_token = (await answer.json())["token"]
    devices = (await _ws(ws_client, "list"))["result"]["devices"]
    device_id = next(d["id"] for d in devices if d["status"] == "pending")
    await _ws(ws_client, "device_confirm", device_id=device_id, accept=True)
    return device_id, {"Authorization": f"Bearer {device_token}"}


def _today() -> str:
    return dt_util.now().date().isoformat()


# ----- templates, modes and defaults ---------------------------------------------------------


async def test_without_template_only_the_calendar_read_only(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any
) -> None:
    device_id, headers = await _phone(client, hass_ws_client, template="custom")
    device = next(
        d for d in (await _ws(hass_ws_client, "list"))["result"]["devices"] if d["id"] == device_id
    )
    assert device["features"] == {
        "calendar": True,
        "reminders": False,
        "lists": False,
        "waste": False,
        "weather": False,
    }
    assert device["permission"] == "view" and device["notify"] is False
    assert device["has_shifts"] is False and device["mode"] == "simple"
    me = await (await client.get(f"{API}me", headers=headers)).json()
    assert me["mode"] == "simple" and me["features"]["calendar"] is True
    assert me["vapid"] == ""  # nothing to push to
    assert (await client.get(f"{API}events?from={_today()}&days=7", headers=headers)).status == 200
    add = {
        "title": "Prova",
        "date": _today(),
        "all_day": True,
        "person": "sofia",
        "category": "scuola",
    }
    assert (await client.post(f"{API}events", json=add, headers=headers)).status == 403
    for path in (
        "lists/abc",
        f"waste?from={_today()}&days=7",
        "weather",
        f"shifts?from={_today()}&days=7",
    ):
        assert (await client.get(f"{API}{path}", headers=headers)).status == 403, path
    assert (
        await client.post(f"{API}push", json={"subscription": SUBSCRIPTION}, headers=headers)
    ).status == 403


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("grandparents", {"mode": "simple", "permission": "add", "has_shifts": True}),
        ("babysitter", {"mode": "simple", "permission": "view", "has_shifts": False}),
        ("relative", {"mode": "full", "permission": "edit_own", "notify": True}),
    ],
)
async def test_templates(
    hass: HomeAssistant,
    hass_ws_client: Any,
    family: MockConfigEntry,
    template: str,
    expected: dict[str, Any],
) -> None:
    created = await _ws(
        hass_ws_client,
        "invite_create",
        invite={
            "name": "Prova",
            "persons": ["sofia"],
            "categories": ["scuola"],
            "template": template,
        },
    )
    assert created["success"], created
    invite = (await _ws(hass_ws_client, "list"))["result"]["invites"][0]
    assert invite["template"] == template
    for key, value in expected.items():
        assert invite[key] == value, key
    assert invite["features"]["calendar"] is True
    assert invite["features"]["lists"] is False and invite["lists"] == []
    if template == "babysitter":
        assert not any(v for k, v in invite["features"].items() if k != "calendar")


async def test_a_template_stays_editable(
    hass: HomeAssistant, hass_ws_client: Any, family: MockConfigEntry
) -> None:
    created = await _ws(
        hass_ws_client,
        "invite_create",
        invite={
            "name": "Prova",
            "persons": ["sofia"],
            "categories": ["scuola"],
            "template": "grandparents",
            "has_shifts": False,
            "mode": "full",
            "features": {"weather": True},
        },
    )
    assert created["success"]
    invite = (await _ws(hass_ws_client, "list"))["result"]["invites"][0]
    assert invite["has_shifts"] is False and invite["mode"] == "full"
    assert invite["features"]["weather"] is True and invite["features"]["calendar"] is True


@pytest.mark.parametrize(
    "bad",
    [
        {"mode": "admin"},
        {"template": "superuser"},
        {"features": {"settings": True}},
        {"features": {"calendar": "yes"}},
        {"lists": ["todo.non_della_famiglia"]},
        {"lists_edit": "si"},
    ],
)
async def test_invalid_choices_are_refused(
    hass: HomeAssistant, hass_ws_client: Any, family: MockConfigEntry, bad: dict[str, Any]
) -> None:
    created = await _ws(
        hass_ws_client,
        "invite_create",
        invite={"name": "Prova", "persons": ["sofia"], "categories": ["scuola"], **bad},
    )
    assert not created["success"] and created["error"]["code"] == "invalid"


async def test_the_calendar_can_be_turned_off(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any
) -> None:
    _, headers = await _phone(
        client,
        hass_ws_client,
        template="custom",
        permission="edit_own",
        features={"calendar": False, "weather": True},
    )
    assert (await client.get(f"{API}events?from={_today()}&days=7", headers=headers)).status == 403
    add = {
        "title": "Prova",
        "date": _today(),
        "all_day": True,
        "person": "sofia",
        "category": "scuola",
    }
    assert (await client.post(f"{API}events", json=add, headers=headers)).status == 403
    assert (await client.get(f"{API}weather", headers=headers)).status == 200


async def test_the_adult_changes_the_functions_later(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any
) -> None:
    device_id, headers = await _phone(client, hass_ws_client, template="babysitter")
    assert (await client.get(f"{API}weather", headers=headers)).status == 403
    answer = await _ws(
        hass_ws_client,
        "device_update",
        device_id=device_id,
        changes={
            "features": {"calendar": True, "weather": True},
            "mode": "full",
            "template": "relative",
        },
    )
    assert answer["success"], answer
    assert (await client.get(f"{API}weather", headers=headers)).status == 200
    me = await (await client.get(f"{API}me", headers=headers)).json()
    assert me["mode"] == "full" and me["template"] == "relative"


# ----- never for a guest ----------------------------------------------------------------------


async def test_no_admin_function_for_a_guest(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any
) -> None:
    _, headers = await _phone(client, hass_ws_client, template="relative")
    for path in (
        "invites",
        "devices",
        "share",
        "config",
        "settings",
        "guide",
        "log",
        "invite_create",
    ):
        for method in ("GET", "POST"):
            answer = await client.request(method, f"{API}{path}", headers=headers, json={})
            assert answer.status in (404, 405), (method, path, answer.status)
    me = await (await client.get(f"{API}me", headers=headers)).json()
    for secret in ("invites", "devices", "log", "token_hash", "vapid_private", "recipients"):
        assert secret not in me


# ----- lists -------------------------------------------------------------------------------------


async def test_lists_only_the_chosen_ones(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any, todo: dict[str, Any]
) -> None:
    _, headers = await _phone(
        client, hass_ws_client, template="custom", features={"lists": True}, lists=[LISTS[0]]
    )
    raw = await (await client.get(f"{API}me", headers=headers)).text()
    assert "todo." not in raw and "Lavori adulti" not in raw
    me = await (await client.get(f"{API}me", headers=headers)).json()
    assert [(item["name"], item["edit"]) for item in me["lists"]] == [("Spesa", False)]
    list_id = me["lists"][0]["id"]
    answer = await client.get(f"{API}lists/{list_id}", headers=headers)
    assert answer.status == 200
    assert (await answer.json())["items"] == [{"id": "u1", "summary": "Latte", "done": False}]
    # Read only: no adding, no ticking.
    assert (
        await client.post(f"{API}lists/{list_id}", json={"add": "Pane"}, headers=headers)
    ).status == 403
    tick = {"item": "u1", "done": True}
    assert (await client.post(f"{API}lists/{list_id}", json=tick, headers=headers)).status == 403
    # Another list of the family, by its id: refused.
    other = gf.list_id(next(iter(hass.config_entries.async_entries(DOMAIN))).entry_id, LISTS[1])
    answer = await client.get(f"{API}lists/{other}", headers=headers)
    assert answer.status == 403
    assert "SEGRETO" not in await answer.text()
    assert (await client.get(f"{API}lists/{LISTS[1]}", headers=headers)).status == 403


async def test_lists_add_and_tick(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any, todo: dict[str, Any]
) -> None:
    _, headers = await _phone(
        client,
        hass_ws_client,
        template="custom",
        features={"lists": True},
        lists=[LISTS[0]],
        lists_edit=True,
    )
    list_id = (await (await client.get(f"{API}me", headers=headers)).json())["lists"][0]["id"]
    answer = await client.post(f"{API}lists/{list_id}", json={"add": "Pane"}, headers=headers)
    assert answer.status == 200
    assert [i["summary"] for i in (await answer.json())["items"]] == ["Latte", "Pane"]
    answer = await client.post(
        f"{API}lists/{list_id}", json={"item": "u1", "done": True}, headers=headers
    )
    assert (await answer.json())["items"][0]["done"] is True
    assert todo[LISTS[0]][0]["status"] == "completed"
    for bad in (
        {"item": "nessuno", "done": True},
        {"add": ""},
        {"delete": "u1"},
        {"add": "x" * 200},
    ):
        assert (await client.post(f"{API}lists/{list_id}", json=bad, headers=headers)).status in (
            404,
            422,
        )


async def test_lists_turned_off_answer_403(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any, todo: dict[str, Any]
) -> None:
    device_id, headers = await _phone(
        client, hass_ws_client, template="custom", features={"lists": True}, lists=[LISTS[0]]
    )
    list_id = (await (await client.get(f"{API}me", headers=headers)).json())["lists"][0]["id"]
    await _ws(
        hass_ws_client, "device_update", device_id=device_id, changes={"features": {"lists": False}}
    )
    assert (await client.get(f"{API}lists/{list_id}", headers=headers)).status == 403
    assert (await (await client.get(f"{API}me", headers=headers)).json())["lists"] == []


# ----- rubbish days and weather ---------------------------------------------------------------


async def test_waste_days(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any, family: MockConfigEntry
) -> None:
    _, headers = await _phone(client, hass_ws_client, template="custom", features={"waste": True})
    external = family.runtime_data.external
    assert external is not None
    tomorrow = dt_util.now().date() + timedelta(days=1)
    sources = [
        {"id": "a", "type": "rifiuti", "persons": []},
        {"id": "b", "type": "rifiuti", "persons": ["mamma"]},  # only for Mamma: not for this guest
        {"id": "c", "type": "scuola", "persons": []},
    ]

    async def names_on(source: dict[str, Any], day: date) -> list[str]:
        if day != tomorrow:
            return []
        return {"a": ["Carta"], "b": ["SOLO-MAMMA"], "c": ["Gita"]}[source["id"]]

    with (
        patch.object(external, "sources", return_value=sources),
        patch.object(external, "_ha_sources", return_value=[]),
        patch.object(external, "_names_on", side_effect=names_on),
    ):
        answer = await client.get(f"{API}waste?from={_today()}&days=7", headers=headers)
        text = await answer.text()
    assert answer.status == 200
    days = (await answer.json())["days"]
    assert [d["date"] for d in days] == [tomorrow.isoformat()]
    assert [i["label"] for i in days[0]["items"]] == ["Carta"]
    assert "SOLO-MAMMA" not in text and "Gita" not in text
    assert (await client.get(f"{API}waste?from={_today()}&days=99", headers=headers)).status == 422


async def test_weather(hass: HomeAssistant, client: TestClient, hass_ws_client: Any) -> None:
    hass.states.async_set(WEATHER, "sunny", {"temperature": 21, "temperature_unit": "°C"})
    _, headers = await _phone(client, hass_ws_client, template="custom", features={"weather": True})
    answer = await client.get(f"{API}weather", headers=headers)
    assert answer.status == 200
    data = await answer.json()
    assert data["condition"] == "sunny" and "21" in data["line"]
    assert WEATHER not in await answer.text()


# ----- notifications and reminders --------------------------------------------------------------


async def test_reminders_without_notifications(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any, family: MockConfigEntry
) -> None:
    _, headers = await _phone(
        client, hass_ws_client, template="custom", notify=False, features={"reminders": True}
    )
    me = await (await client.get(f"{API}me", headers=headers)).json()
    assert me["vapid"]  # push is needed for the reminders
    assert (
        await client.post(f"{API}push", json={"subscription": SUBSCRIPTION}, headers=headers)
    ).status == 200
    manager = family.runtime_data.guests
    assert manager is not None
    record = {
        "uid": "r1",
        "summary": "Gita",
        "persons": ["sofia"],
        "category": "scuola",
        "start": _today(),
        "end": _today(),
        "all_day": True,
    }
    with patch.object(webpush, "async_send", return_value=webpush.SENT) as send:
        await manager.async_on_reminder(record, "Domani: Gita")
        await hass.async_block_till_done()
        assert send.call_count == 1
        # Changes and new appointments are "notifications": off for this phone.
        await hass.services.async_call(
            DOMAIN,
            "add_event",
            {
                "category": "scuola",
                "summary": "Nuovo",
                "persons": ["sofia"],
                "start": f"{(dt_util.now().date() + timedelta(days=2)).isoformat()} 09:00:00",
                "end": f"{(dt_util.now().date() + timedelta(days=2)).isoformat()} 10:00:00",
            },
            blocking=True,
        )
        await hass.async_block_till_done()
        assert send.call_count == 1


async def test_notifications_without_reminders(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any, family: MockConfigEntry
) -> None:
    _, headers = await _phone(
        client, hass_ws_client, template="custom", notify=True, features={"reminders": False}
    )
    assert (
        await client.post(f"{API}push", json={"subscription": SUBSCRIPTION}, headers=headers)
    ).status == 200
    manager = family.runtime_data.guests
    assert manager is not None
    record = {
        "uid": "r1",
        "summary": "Gita",
        "persons": ["sofia"],
        "category": "scuola",
        "start": _today(),
        "end": _today(),
        "all_day": True,
    }
    with patch.object(webpush, "async_send", return_value=webpush.SENT) as send:
        await manager.async_on_reminder(record, "Domani: Gita")
        await hass.async_block_till_done()
        assert send.call_count == 0


# ----- upgrade from 0.9 -------------------------------------------------------------------------


async def test_phones_of_0_9_become_grandparents(
    hass: HomeAssistant, hass_storage: dict[str, Any], hass_client_no_auth: Any, hass_ws_client: Any
) -> None:
    """An invite and a phone stored by 0.9 (no mode, template or features) keep working, with
    the "Nonni" template and the permissions they had: same token, same choices."""
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it"},
        options={OPT_PERSONS: PERSONS, OPT_CATEGORIES: CATEGORIES, CONF_LANGUAGE: "it"},
    )
    entry.add_to_hass(hass)
    token = "t" * 43
    now = dt_util.utcnow().isoformat()
    scope = {
        "persons": ["sofia"],
        "categories": ["scuola"],
        "permission": "edit_own",
        "approval": "direct",
        "notify": True,
        "family_events": False,
        "has_shifts": False,
        "shift_color": "#8B5CF6",
        "shifts_category": "scuola",
    }
    hass_storage[f"{DOMAIN}.{entry.entry_id}.guests"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}.guests",
        "data": {
            "invites": {
                "i1": {
                    "id": "i1",
                    "name": "Nonna Vecchia",
                    **scope,
                    "created_at": now,
                    "expires_at": now,
                    "status": "used",
                    "token_hash": "x",
                    "device_id": "d1",
                    "closed_at": now,
                    "replaces": None,
                },
            },
            "devices": {
                "d1": {
                    "id": "d1",
                    "invite_id": "i1",
                    "name": "Nonna Vecchia",
                    "label": "Android",
                    "activated_at": now,
                    "last_seen": now,
                    "status": "active",
                    "token_hash": token_hash(token),
                    "token_at": now,
                    "prev_hash": None,
                    "prev_until": None,
                    **scope,
                    "person_id": None,
                    "push": None,
                },
            },
            "pending": {},
            "log": [],
            "vapid": {"public": "p", "private": "q"},
        },
    }
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    client = await hass_client_no_auth()
    answer = await client.get(f"{API}me", headers={"Authorization": f"Bearer {token}"})
    assert answer.status == 200
    me = await answer.json()
    assert me["template"] == "grandparents" and me["mode"] == "simple"
    assert me["permission"] == "edit_own" and me["approval"] == "direct"
    assert me["features"]["calendar"] is True and me["features"]["reminders"] is True
    assert me["features"]["lists"] is False
    assert (
        await client.get(
            f"{API}events?from={_today()}&days=7", headers={"Authorization": f"Bearer {token}"}
        )
    ).status == 200
    listed = (await _ws(hass_ws_client, "list"))["result"]
    assert listed["devices"][0]["template"] == "grandparents"
    assert listed["invites"][0]["template"] == "grandparents"
    stored = hass_storage[f"{DOMAIN}.{entry.entry_id}.guests"]["data"]
    assert stored["devices"]["d1"]["features"]["reminders"] is True


async def test_a_0_9_request_keeps_the_old_defaults(
    hass: HomeAssistant, hass_ws_client: Any, family: MockConfigEntry
) -> None:
    """An invite asked as 0.9 asked it (no template, mode or features): as before."""
    created = await _ws(
        hass_ws_client,
        "invite_create",
        invite={"name": "Prova", "persons": ["sofia"], "categories": ["scuola"]},
    )
    assert created["success"]
    invite = (await _ws(hass_ws_client, "list"))["result"]["invites"][0]
    assert invite["notify"] is True and invite["permission"] == "view"
    assert invite["template"] == "grandparents" and invite["features"]["reminders"] is True


def test_upgrade_keeps_notify_off() -> None:
    item: dict[str, Any] = {"notify": False}
    assert gf.upgrade(item) is True
    assert item["features"]["reminders"] is False and item["template"] == "grandparents"
    assert gf.upgrade(item) is False
