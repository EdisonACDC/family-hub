"""Invites for the grandparents: the guest web app, its API and the adults' commands.

Names are invented. "Nonna Èlia 👵" stands for the grandmother; Sofia is a child, Mamma an adult.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.family_hub import guests as guests_module
from custom_components.family_hub import webpush
from custom_components.family_hub.const import (
    CONF_FAMILY_NAME,
    CONF_FIRST_WEEKDAY,
    CONF_LANGUAGE,
    DOMAIN,
    OPT_CATEGORIES,
    OPT_PERSONS,
)
from custom_components.family_hub.diagnostics import async_get_config_entry_diagnostics
from custom_components.family_hub.guests import (
    ActivationGuard,
    RateLimiter,
    clean_event,
    describe_device,
    guest_hub,
    token_hash,
)

API = "/api/family_hub/guest/api/"
ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/131.0 Mobile Safari"
IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 "
    "Version/18.1 Mobile/15E148 Safari/604.1"
)
GRANDMA = "Nonna Èlia 👵"
PERSONS = [
    {"id": "sofia", "name": "Sofia", "color": "#FF8800", "role": "child"},
    {
        "id": "mamma",
        "name": "Mamma Segreta",
        "color": "#123456",
        "role": "adult",
        "phone_notify": "mobile_app_telefono_mamma",
    },
]
CATEGORIES = [
    {"id": "scuola", "name": "Scuola", "color": "#10B981"},
    {"id": "asilo", "name": "Asilo", "color": "#22C55E"},
    {"id": "dottore", "name": "Dottore", "color": "#EF4444"},
    {"id": "lavoro", "name": "Lavoro riservato", "color": "#654321"},
]
GOOD_SUBSCRIPTION = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/abc123",
    "keys": {"p256dh": "B" + "A" * 86, "auth": "c2VjcmV0YXV0aDEyMzQ"},
}


@pytest.fixture
async def family(hass: HomeAssistant) -> MockConfigEntry:
    assert await async_setup_component(hass, "http", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
        options={OPT_PERSONS: PERSONS, OPT_CATEGORIES: CATEGORIES, CONF_LANGUAGE: "it"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.fixture
async def client(
    hass: HomeAssistant, family: MockConfigEntry, hass_client_no_auth: Any
) -> AsyncIterator[TestClient]:
    yield await hass_client_no_auth()


@pytest.fixture(autouse=True)
def no_real_push() -> Any:
    with patch.object(webpush, "async_send", return_value=webpush.SENT) as send:
        yield send


@pytest.fixture(autouse=True)
def fresh_limits(hass: HomeAssistant) -> None:
    """Every test starts with empty rate limits."""
    hass.data.setdefault(DOMAIN, {}).pop("guests", None)


def _day(offset: int) -> str:
    return (dt_util.now().date() + timedelta(days=offset)).isoformat()


def _logged(caplog: pytest.LogCaptureFixture) -> str:
    """Everything logged, except Home Assistant's own websocket trace (which, only with debug
    logging switched on for websocket_api, repeats every message, the adult's link included)."""
    return " | ".join(
        record.getMessage()
        for record in caplog.records
        # Also left out: the test library's fake storage, which logs what it is given.
        if not record.name.startswith(
            ("homeassistant.components.websocket_api", "pytest_homeassistant_custom_component")
        )
    )


def _unlimited(hass: HomeAssistant) -> None:
    hub = guest_hub(hass)
    hub.read_limit = RateLimiter(10_000)
    hub.write_limit = RateLimiter(10_000)


def _manager(entry: MockConfigEntry) -> Any:
    return entry.runtime_data.guests


async def _ws(hass: HomeAssistant, ws_client: Any, command: str, **data: Any) -> dict[str, Any]:
    client = await ws_client()
    await client.send_json_auto_id({"type": f"family_hub/guest/{command}", **data})
    return await client.receive_json()


async def _invite(hass: HomeAssistant, ws_client: Any, **overrides: Any) -> tuple[str, str]:
    """Make an invite; returns its id and the token from the link."""
    invite = {
        "name": GRANDMA,
        "persons": ["sofia"],
        "categories": ["scuola", "asilo"],
        "permission": "edit_own",
        "approval": "approve",
        "notify": True,
        **overrides,
    }
    answer = await _ws(hass, ws_client, "invite_create", invite=invite)
    assert answer["success"], answer
    link = answer["result"]["link"]
    assert "/api/family_hub/guest/#i=" in link
    return answer["result"]["id"], link.split("#i=", 1)[1]


async def _activate(client: TestClient, token: str, agent: str = ANDROID) -> Any:
    return await client.post(f"{API}activate", json={"token": token}, headers={"User-Agent": agent})


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _device(
    hass: HomeAssistant, client: TestClient, ws_client: Any, **overrides: Any
) -> tuple[str, str]:
    """An invite, opened by a phone and confirmed by an adult. Returns device id and token."""
    _, invite_token = await _invite(hass, ws_client, **overrides)
    answer = await _activate(client, invite_token)
    assert answer.status == 200
    token = (await answer.json())["token"]
    family = hass.config_entries.async_entries(DOMAIN)[0]
    (device_id,) = [d["id"] for d in _manager(family).devices.values() if d["status"] == "pending"]
    confirmed = await _ws(hass, ws_client, "device_confirm", device_id=device_id, accept=True)
    assert confirmed["success"]
    return device_id, token


async def _family_event(
    hass: HomeAssistant, category: str, persons: list[str], summary: str, day: int = 3
) -> None:
    await hass.services.async_call(
        DOMAIN,
        "add_event",
        {
            "category": category,
            "summary": summary,
            "start": f"{_day(day)} 10:00:00",
            "end": f"{_day(day)} 11:00:00",
            "persons": persons,
            "location": "Via Esempio 1",
            "description": "nota privata della famiglia",
        },
        blocking=True,
    )


async def _list(client: TestClient, token: str, **query: Any) -> Any:
    params = {"from": _day(0), "days": "14", **query}
    return await client.get(f"{API}events", params=params, headers=_auth(token))


def _new(**overrides: Any) -> dict[str, Any]:
    return {
        "title": "Merenda dalla nonna",
        "person": "sofia",
        "category": "scuola",
        "date": _day(2),
        "all_day": False,
        "start": "16:00",
        "end": "17:30",
        "location": "Casa della nonna",
        "note": "Porto i biscotti",
        **overrides,
    }


# ----- nothing changes without invites ---------------------------------------


async def test_without_invites_no_guest_address_answers(
    hass: HomeAssistant, client: TestClient
) -> None:
    for path in (
        "/api/family_hub/guest/",
        f"{API}me",
        f"{API}events",
        "/api/family_hub/guest/sw.js",
    ):
        assert (await client.get(path)).status == 404
    assert (await client.post(f"{API}activate", json={"token": "x" * 43})).status == 404
    assert not guest_hub(hass).views_registered


async def test_storage_of_version_0_8_loads_unchanged(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """An events file written by 0.8 (no "added_by") loads as it is; no guest file is made."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
        options={OPT_PERSONS: PERSONS, OPT_CATEGORIES: CATEGORIES},
    )
    old = {
        "uid": "a" * 32,
        "category": "scuola",
        "summary": "Gita",
        "description": "",
        "location": "",
        "persons": ["sofia"],
        "start": f"{_day(3)}",
        "end": f"{_day(4)}",
        "all_day": True,
        "reminder_offsets": None,
        "reminders_off": False,
    }
    hass_storage[f"{DOMAIN}.{entry.entry_id}.events"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}.events",
        "data": {"events": {old["uid"]: old}},
    }
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.store.events == {old["uid"]: old}
    assert f"{DOMAIN}.{entry.entry_id}.guests" not in hass_storage
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert "guests" not in diagnostics


# ----- invites ---------------------------------------------------------------------


async def test_invite_is_kept_only_as_a_hash(
    hass: HomeAssistant,
    client: TestClient,
    hass_ws_client: Any,
    hass_storage: dict[str, Any],
    family: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    _, token = await _invite(hass, hass_ws_client)
    assert len(token) >= 43  # 256 bits
    await hass.async_block_till_done()
    stored = json.dumps(hass_storage[f"{DOMAIN}.{family.entry_id}.guests"], ensure_ascii=False)
    assert token not in stored
    assert token_hash(token) in stored
    assert token not in _logged(caplog)
    listed = await _ws(hass, hass_ws_client, "list")
    assert token not in json.dumps(listed) and token_hash(token) not in json.dumps(listed)
    assert listed["result"]["invites"][0]["status"] == "open"


async def test_invite_needs_known_persons_and_calendars(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any
) -> None:
    for bad in (
        {"persons": ["nessuno"]},
        {"categories": ["inventato"]},
        {"persons": []},
        {"permission": "admin"},
        {"expires_days": 0},
        {"name": "x" * 41},
    ):
        answer = await _ws(
            hass,
            hass_ws_client,
            "invite_create",
            invite={"name": GRANDMA, "persons": ["sofia"], "categories": ["scuola"], **bad},
        )
        assert not answer["success"], bad


async def test_commands_need_an_administrator(
    hass: HomeAssistant,
    client: TestClient,
    hass_ws_client: Any,
    hass_read_only_access_token: str,
) -> None:
    ws = await hass_ws_client(hass, hass_read_only_access_token)
    for command in ("list", "invite_create", "device_confirm", "pending_decide"):
        await ws.send_json_auto_id({"type": f"family_hub/guest/{command}"})
        answer = await ws.receive_json()
        assert not answer["success"]
        assert answer["error"]["code"] in ("unauthorized", "invalid_format")


async def test_an_invite_works_once_only(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any
) -> None:
    _, token = await _invite(hass, hass_ws_client)
    first = await _activate(client, token)
    assert first.status == 200
    assert (await first.json())["status"] == "pending"
    second = await _activate(client, token, IPHONE)
    assert second.status == 403
    assert await second.json() == {"error": "invite_invalid"}


async def test_an_expired_invite_is_refused(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any, family: MockConfigEntry
) -> None:
    invite_id, token = await _invite(hass, hass_ws_client)
    invite = _manager(family).invites[invite_id]
    # Two invites keep the web app on while this one expires.
    await _invite(hass, hass_ws_client)
    invite["expires_at"] = (dt_util.utcnow() - timedelta(minutes=1)).isoformat()
    answer = await _activate(client, token)
    assert answer.status == 403
    listed = await _ws(hass, hass_ws_client, "list")
    assert {i["id"]: i["status"] for i in listed["result"]["invites"]}[invite_id] == "expired"


async def test_a_second_try_with_a_used_invite_is_logged_and_told_to_adults(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any, family: MockConfigEntry
) -> None:
    calls: list[Any] = []
    hass.services.async_register("notify", "mobile_app_telefono_mamma", calls.append)
    _, token = await _invite(hass, hass_ws_client)
    assert (await _activate(client, token)).status == 200
    await hass.async_block_till_done()
    calls.clear()  # the "phone waiting" notice
    for _ in range(3):
        answer = await _activate(client, token, IPHONE)
        assert answer.status == 403 and await answer.json() == {"error": "invite_invalid"}
    await hass.async_block_till_done()
    log = (await _ws(hass, hass_ws_client, "list"))["result"]["log"]
    tries = [e for e in log if e["kind"] == "attempt_used"]
    assert len(tries) == 3
    assert tries[0]["name"] == GRANDMA and tries[0]["detail"] == "iPhone · Safari"
    # The adults are told once, not three times.
    (call,) = calls
    assert "già usato" in call.data["message"] and "iPhone · Safari" in call.data["message"]
    assert "actions" not in call.data["data"]
    # Still only one device: the second phone got nothing.
    assert len(_manager(family).devices) == 1


async def test_a_try_with_an_expired_or_cancelled_invite_is_logged(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any, family: MockConfigEntry
) -> None:
    expired_id, expired = await _invite(hass, hass_ws_client)
    cancelled_id, cancelled = await _invite(hass, hass_ws_client, name="Nonno")
    await _invite(hass, hass_ws_client, name="Zia")  # keeps the web app on
    _manager(family).invites[expired_id]["expires_at"] = (
        dt_util.utcnow() - timedelta(minutes=1)
    ).isoformat()
    await _ws(hass, hass_ws_client, "invite_revoke", invite_id=cancelled_id)
    assert (await _activate(client, expired)).status == 403
    assert (await _activate(client, cancelled)).status == 403
    log = (await _ws(hass, hass_ws_client, "list"))["result"]["log"]
    kinds = {(e["kind"], e["name"]) for e in log}
    assert ("attempt_expired", GRANDMA) in kinds and ("attempt_revoked", "Nonno") in kinds
    # An unknown token is refused without a log entry (there is no invite to name).
    assert (await _activate(client, "x" * 43)).status == 403
    assert len((await _ws(hass, hass_ws_client, "list"))["result"]["log"]) == len(log)


async def test_the_week_starts_as_the_family_chose(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any, family: MockConfigEntry
) -> None:
    _, token = await _device(hass, client, hass_ws_client)
    me = await (await client.get(f"{API}me", headers=_auth(token))).json()
    assert me["week_from_today"] is True  # the family's default
    hass.config_entries.async_update_entry(
        family, options={**family.options, "week_from_today": False}
    )
    await hass.async_block_till_done()
    me = await (await client.get(f"{API}me", headers=_auth(token))).json()
    assert me["week_from_today"] is False


async def test_a_revoked_invite_turns_the_web_app_off(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any
) -> None:
    invite_id, token = await _invite(hass, hass_ws_client)
    assert (await client.get("/api/family_hub/guest/")).status == 200
    assert (await _ws(hass, hass_ws_client, "invite_revoke", invite_id=invite_id))["success"]
    assert (await client.get("/api/family_hub/guest/")).status == 404
    assert (await _activate(client, token)).status == 404


# ----- activation and confirmation ---------------------------------------------------


async def test_activation_waits_for_an_adult(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any, family: MockConfigEntry
) -> None:
    calls: list[Any] = []
    hass.services.async_register("notify", "mobile_app_telefono_mamma", calls.append)
    _, invite_token = await _invite(hass, hass_ws_client)
    answer = await _activate(client, invite_token, IPHONE)
    token = (await answer.json())["token"]
    await hass.async_block_till_done()
    me = await client.get(f"{API}me", headers=_auth(token))
    assert await me.json() == {"status": "pending"}
    assert (await _list(client, token)).status == 403
    (device,) = _manager(family).devices.values()
    assert device["label"] == "iPhone · Safari"
    assert device["name"] == GRANDMA
    # The adult's phone is asked, with Conferma / Rifiuta.
    (call,) = calls
    assert "iPhone · Safari" in call.data["message"] and GRANDMA in call.data["message"]
    actions = [a["action"] for a in call.data["data"]["actions"]]
    assert actions == [f"FH_GUEST_CONFIRM_{device['id']}", f"FH_GUEST_REJECT_{device['id']}"]
    notifications = hass.states.async_all("persistent_notification")
    assert notifications or hass.data.get("persistent_notification")
    # The phone's button confirms it.
    hass.bus.async_fire("mobile_app_notification_action", {"action": actions[0]})
    await hass.async_block_till_done()
    assert device["status"] == "active"
    me = await (await client.get(f"{API}me", headers=_auth(token))).json()
    assert me["status"] == "active" and me["name"] == GRANDMA


async def test_a_rejected_phone_gets_nothing(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any, family: MockConfigEntry
) -> None:
    _, invite_token = await _invite(hass, hass_ws_client)
    token = (await (await _activate(client, invite_token)).json())["token"]
    (device_id,) = _manager(family).devices
    answer = await _ws(hass, hass_ws_client, "device_confirm", device_id=device_id, accept=False)
    assert answer["success"]
    # With another invite open, the phone is told why; with nothing left, the app is off (404).
    await _invite(hass, hass_ws_client)
    me = await client.get(f"{API}me", headers=_auth(token))
    assert me.status == 403 and await me.json() == {"error": "rejected"}
    assert (await _list(client, token)).status == 403


async def test_an_unknown_token_is_refused(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any
) -> None:
    await _invite(hass, hass_ws_client)
    for headers in ({}, {"Authorization": "Bearer nonesiste"}, {"Authorization": "Basic abc"}):
        answer = await client.get(f"{API}me", headers=headers)
        assert answer.status == 401
        assert await answer.json() == {"error": "unknown"}


# ----- the filter on the server ------------------------------------------------------


async def test_a_guest_sees_only_its_persons_and_calendars(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any
) -> None:
    _, token = await _device(hass, client, hass_ws_client)
    await _family_event(hass, "scuola", ["sofia"], "Recita di Sofia")
    await _family_event(hass, "scuola", ["sofia", "mamma"], "Colloquio insegnanti")
    await _family_event(hass, "scuola", ["mamma"], "Riunione di Mamma")
    await _family_event(hass, "lavoro", ["mamma"], "Cena di lavoro")
    await _family_event(hass, "dottore", ["sofia"], "Vaccino di Sofia")
    await _family_event(hass, "scuola", [], "Senza persone")
    answer = await _list(client, token)
    assert answer.status == 200
    events = (await answer.json())["events"]
    assert sorted(e["title"] for e in events) == ["Colloquio insegnanti", "Recita di Sofia"]
    for event in events:
        assert event["persons"] == ["sofia"]
        assert set(event) == {
            "id",
            "title",
            "start",
            "end",
            "all_day",
            "category",
            "persons",
            "location",
            "added_by",
            "mine",
            "status",
        }
    text = json.dumps(await answer.json(), ensure_ascii=False)
    for secret in ("Mamma", "mamma", "#123456", "Lavoro", "Vaccino", "nota privata", "mobile_app"):
        assert secret not in text
    me = await (await client.get(f"{API}me", headers=_auth(token))).json()
    me_text = json.dumps(me, ensure_ascii=False)
    assert [p["id"] for p in me["persons"]] == ["sofia"]
    assert [c["id"] for c in me["categories"]] == ["scuola", "asilo"]
    for secret in ("Mamma", "#123456", "Lavoro", "dottore", "mobile_app", "ha_user"):
        assert secret not in me_text


async def test_changed_parameters_do_not_widen_what_a_guest_sees(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any
) -> None:
    assert await async_setup_component(hass, "api", {})
    _, token = await _device(hass, client, hass_ws_client)
    await _family_event(hass, "lavoro", ["mamma"], "Cena di lavoro")
    for query in (
        {"person": "mamma"},
        {"category": "lavoro"},
        {"days": "1000"},
        {"days": "-1"},
        {"from": "ieri"},
        {"from": "2026-02-30"},
    ):
        answer = await _list(client, token, **query)
        assert answer.status == 422, query
        assert await answer.json() == {"error": "invalid"}
    # Anything else of Home Assistant is not reachable with a device token.
    for path in ("/api/states", "/api/config", "/api/services"):
        assert (await client.get(path, headers=_auth(token))).status == 401


async def test_a_guest_cannot_write_outside_its_scope(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any, family: MockConfigEntry
) -> None:
    _, token = await _device(hass, client, hass_ws_client, approval="direct")
    _unlimited(hass)
    for bad, status in (
        ({"person": "mamma"}, 403),
        ({"category": "lavoro"}, 403),
        ({"category": "dottore"}, 403),
        ({"title": ""}, 422),
        ({"title": "x" * 81}, 422),
        ({"note": "x" * 501}, 422),
        ({"date": "2026-13-01"}, 422),
        ({"date": _day(-5)}, 422),
        ({"start": "18:00", "end": "17:00"}, 422),
        ({"start": "25:00"}, 422),
        ({"rrule": "FREQ=DAILY"}, 422),
        ({"persons": ["mamma"]}, 422),
    ):
        answer = await client.post(f"{API}events", json=_new(**bad), headers=_auth(token))
        assert answer.status == status, bad
        assert set(await answer.json()) == {"error"}
    assert family.runtime_data.store.events == {}
    not_json = await client.post(f"{API}events", data="title=x", headers=_auth(token))
    assert not_json.status == 415
    huge = await client.post(f"{API}events", json=_new(note="x" * 9000), headers=_auth(token))
    assert huge.status == 413


# ----- permissions ----------------------------------------------------------------


async def test_view_only_cannot_add(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any
) -> None:
    _, token = await _device(hass, client, hass_ws_client, permission="view")
    answer = await client.post(f"{API}events", json=_new(), headers=_auth(token))
    assert answer.status == 403


async def test_add_without_edit_cannot_change(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any, family: MockConfigEntry
) -> None:
    _, token = await _device(hass, client, hass_ws_client, permission="add", approval="direct")
    answer = await client.post(f"{API}events", json=_new(), headers=_auth(token))
    assert answer.status == 201
    uid = (await answer.json())["event"]["id"]
    assert (
        await client.put(f"{API}events/{uid}", json=_new(title="Altro"), headers=_auth(token))
    ).status == 403
    assert (await client.delete(f"{API}events/{uid}", headers=_auth(token))).status == 403
    assert uid in family.runtime_data.store.events


async def test_edit_only_its_own_appointments(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any, family: MockConfigEntry
) -> None:
    _, token = await _device(hass, client, hass_ws_client, approval="direct")
    _unlimited(hass)
    await _family_event(hass, "scuola", ["sofia"], "Recita di Sofia")
    (family_uid,) = family.runtime_data.store.events
    answer = await client.post(f"{API}events", json=_new(), headers=_auth(token))
    own = (await answer.json())["event"]
    assert own["mine"] and own["added_by"] == GRANDMA and own["note"] == "Porto i biscotti"
    record = family.runtime_data.store.events[own["id"]]
    assert record["added_by"]["name"] == GRANDMA
    # The family's appointment: not found for this phone, so not changed.
    assert (
        await client.put(f"{API}events/{family_uid}", json=_new(), headers=_auth(token))
    ).status == 404
    assert (await client.delete(f"{API}events/{family_uid}", headers=_auth(token))).status == 404
    # Its own one: changed, moved to another allowed calendar, then deleted.
    changed = await client.put(
        f"{API}events/{own['id']}",
        json=_new(title="Merenda spostata", start="17:00", end="18:00"),
        headers=_auth(token),
    )
    assert changed.status == 200
    assert family.runtime_data.store.events[own["id"]]["summary"] == "Merenda spostata"
    moved = await client.put(
        f"{API}events/{own['id']}", json=_new(category="asilo"), headers=_auth(token)
    )
    new_id = (await moved.json())["event"]["id"]
    assert family.runtime_data.store.events[new_id]["category"] == "asilo"
    assert own["id"] not in family.runtime_data.store.events
    assert (await client.delete(f"{API}events/{new_id}", headers=_auth(token))).status == 200
    assert list(family.runtime_data.store.events) == [family_uid]
    # Family Hub's calendar shows who added it.
    await client.post(f"{API}events", json=_new(), headers=_auth(token))
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": "calendar.family_hub_scuola",
            "start_date_time": f"{_day(0)} 00:00:00",
            "end_date_time": f"{_day(10)} 00:00:00",
        },
        blocking=True,
        return_response=True,
    )
    events = response["calendar.family_hub_scuola"]["events"]
    assert any(e["summary"] == "Merenda dalla nonna" for e in events)


async def test_an_adult_can_change_the_permissions(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any
) -> None:
    device_id, token = await _device(hass, client, hass_ws_client)
    answer = await _ws(
        hass,
        hass_ws_client,
        "device_update",
        device_id=device_id,
        changes={"name": "Nonna Rosa", "permission": "view", "categories": ["asilo"]},
    )
    assert answer["success"]
    me = await (await client.get(f"{API}me", headers=_auth(token))).json()
    assert me["name"] == "Nonna Rosa" and me["permission"] == "view"
    assert [c["id"] for c in me["categories"]] == ["asilo"]
    bad = await _ws(
        hass, hass_ws_client, "device_update", device_id=device_id, changes={"persons": ["nessuno"]}
    )
    assert not bad["success"]


# ----- approval ---------------------------------------------------------------------


async def test_appointments_wait_for_approval(
    hass: HomeAssistant,
    client: TestClient,
    hass_ws_client: Any,
    family: MockConfigEntry,
    no_real_push: Any,
) -> None:
    calls: list[Any] = []
    hass.services.async_register("notify", "mobile_app_telefono_mamma", calls.append)
    device_id, token = await _device(hass, client, hass_ws_client)
    family.runtime_data.guests.devices[device_id]["push"] = GOOD_SUBSCRIPTION
    answer = await client.post(f"{API}events", json=_new(), headers=_auth(token))
    assert answer.status == 201
    item = (await answer.json())["event"]
    assert item["status"] == "pending"
    assert family.runtime_data.store.events == {}
    await hass.async_block_till_done()
    assert any("Merenda dalla nonna" in c.data["message"] for c in calls)
    listed = (await (await _list(client, token)).json())["events"]
    assert [(e["title"], e["status"]) for e in listed] == [("Merenda dalla nonna", "pending")]
    queue = (await _ws(hass, hass_ws_client, "list"))["result"]["pending"]
    assert [p["device"] for p in queue] == [GRANDMA]
    # The adult changes the time and approves.
    changes = {**_new(), "start": "15:00", "end": "16:00"}
    answer = await _ws(
        hass, hass_ws_client, "pending_decide", pending_id=item["id"], accept=True, changes=changes
    )
    assert answer["success"]
    await hass.async_block_till_done()
    (record,) = family.runtime_data.store.events.values()
    assert record["added_by"]["name"] == GRANDMA
    assert "T15:00:00" in record["start"]
    listed = (await (await _list(client, token)).json())["events"]
    assert [(e["status"], e["added_by"]) for e in listed] == [("ok", GRANDMA)]
    bodies = [call.args[2]["body"] for call in no_real_push.call_args_list]
    assert any(body.startswith("Approvato: Merenda dalla nonna") for body in bodies)


async def test_a_rejected_appointment_is_dropped(
    hass: HomeAssistant,
    client: TestClient,
    hass_ws_client: Any,
    family: MockConfigEntry,
    no_real_push: Any,
) -> None:
    device_id, token = await _device(hass, client, hass_ws_client)
    family.runtime_data.guests.devices[device_id]["push"] = GOOD_SUBSCRIPTION
    item = (await (await client.post(f"{API}events", json=_new(), headers=_auth(token))).json())[
        "event"
    ]
    hass.bus.async_fire(
        "mobile_app_notification_action", {"action": f"FH_GUEST_DECLINE_{item['id']}"}
    )
    await hass.async_block_till_done()
    assert family.runtime_data.store.events == {}
    assert family.runtime_data.guests.pending == {}
    assert (await (await _list(client, token)).json())["events"] == []
    bodies = [call.args[2]["body"] for call in no_real_push.call_args_list]
    assert any(body.startswith("Non approvato: Merenda dalla nonna") for body in bodies)


async def test_direct_appointments_go_straight_in(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any, family: MockConfigEntry
) -> None:
    _, token = await _device(hass, client, hass_ws_client, approval="direct")
    item = await (
        await client.post(
            f"{API}events", json=_new(all_day=True, start=None, end=None), headers=_auth(token)
        )
    ).json()
    assert item == {"error": "invalid"}  # null times are refused, not ignored
    answer = await client.post(
        f"{API}events",
        json={k: v for k, v in _new(all_day=True).items() if k not in ("start", "end")},
        headers=_auth(token),
    )
    assert answer.status == 201
    (record,) = family.runtime_data.store.events.values()
    assert record["all_day"] and record["start"] == _day(2) and record["end"] == _day(3)


# ----- switching off ------------------------------------------------------------------


async def test_disabling_a_phone_works_at_once(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any, family: MockConfigEntry
) -> None:
    device_id, token = await _device(hass, client, hass_ws_client)
    await client.post(f"{API}events", json=_new(), headers=_auth(token))
    assert (await _list(client, token)).status == 200
    assert (await _ws(hass, hass_ws_client, "device_disable", device_id=device_id))["success"]
    # The only device is off and no invite is open: the web app is off altogether.
    assert (await _list(client, token)).status == 404
    assert family.runtime_data.guests.pending == {}
    # Another invite keeps the app on: the phone is told it is off.
    await _invite(hass, hass_ws_client)
    me = await client.get(f"{API}me", headers=_auth(token))
    assert me.status == 403 and await me.json() == {"error": "disabled"}


async def test_a_disabled_phone_is_refused_while_others_work(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any
) -> None:
    device_id, token = await _device(hass, client, hass_ws_client)
    _, other = await _device(hass, client, hass_ws_client, name="Nonno")
    await _ws(hass, hass_ws_client, "device_disable", device_id=device_id)
    answer = await _list(client, token)
    assert answer.status == 403 and await answer.json() == {"error": "disabled"}
    assert (await client.post(f"{API}events", json=_new(), headers=_auth(token))).status == 403
    assert (await _list(client, other)).status == 200


# ----- limits and tokens -----------------------------------------------------------------


async def test_reads_and_writes_are_limited(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any
) -> None:
    _, token = await _device(hass, client, hass_ws_client, approval="direct")
    statuses = [(await _list(client, token)).status for _ in range(61)]
    assert statuses[:59].count(200) == 59 and statuses[-1] == 429
    guest_hub(hass).read_limit = RateLimiter(60)
    guest_hub(hass).write_limit = RateLimiter(10)  # the activation counted as a write
    statuses = [
        (await client.post(f"{API}events", json=_new(), headers=_auth(token))).status
        for _ in range(11)
    ]
    assert statuses.count(201) == 10 and statuses[-1] == 429


async def test_failed_activations_block_the_address(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any
) -> None:
    _, good = await _invite(hass, hass_ws_client)
    guest_hub(hass).write_limit = RateLimiter(1000)
    for _ in range(10):
        assert (await _activate(client, "sbagliato" * 5)).status == 403
    # Blocked now, even with the right invite.
    assert (await _activate(client, good)).status == 429


def test_limiters_forget_after_their_window() -> None:
    limiter = RateLimiter(2, 60)
    assert limiter.allow("a", 0) and limiter.allow("a", 1) and not limiter.allow("a", 2)
    assert limiter.allow("a", 61)
    guard = ActivationGuard(attempts=3, block_seconds=100)
    for moment in (0, 1, 2):
        guard.failed("1.2.3.4", moment)
    assert guard.blocked("1.2.3.4", 50)
    assert not guard.blocked("1.2.3.4", 103)


async def test_the_device_token_rotates_every_30_days(
    hass: HomeAssistant,
    client: TestClient,
    hass_ws_client: Any,
    family: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    device_id, token = await _device(hass, client, hass_ws_client)
    me = await (await client.get(f"{API}me", headers=_auth(token))).json()
    assert "token" not in me
    device = family.runtime_data.guests.devices[device_id]
    device["token_at"] = (dt_util.utcnow() - timedelta(days=31)).isoformat()
    me = await (await client.get(f"{API}me", headers=_auth(token))).json()
    new = me["token"]
    assert new != token
    assert (await _list(client, new)).status == 200
    # The old one works for a short while, then no more.
    assert (await _list(client, token)).status == 200
    device["prev_until"] = (dt_util.utcnow() - timedelta(seconds=1)).isoformat()
    assert (await _list(client, token)).status == 401
    await hass.async_block_till_done()
    stored = json.dumps(hass_storage[f"{DOMAIN}.{family.entry_id}.guests"])
    assert new not in stored and token not in stored


async def test_no_token_in_storage_logs_or_diagnostics(
    hass: HomeAssistant,
    client: TestClient,
    hass_ws_client: Any,
    family: MockConfigEntry,
    hass_storage: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    _, invite_token = await _invite(hass, hass_ws_client)
    device_token = (await (await _activate(client, invite_token)).json())["token"]
    (device_id,) = family.runtime_data.guests.devices
    await client.post(
        f"{API}push", json={"subscription": GOOD_SUBSCRIPTION}, headers=_auth(device_token)
    )
    await _ws(hass, hass_ws_client, "device_confirm", device_id=device_id, accept=True)
    await client.post(
        f"{API}push", json={"subscription": GOOD_SUBSCRIPTION}, headers=_auth(device_token)
    )
    await hass.async_block_till_done()
    stored = json.dumps(hass_storage[f"{DOMAIN}.{family.entry_id}.guests"])
    diagnostics = json.dumps(await async_get_config_entry_diagnostics(hass, family))
    vapid_private = family.runtime_data.guests.vapid["private"]
    for secret in (invite_token, device_token):
        assert secret not in stored and secret not in _logged(caplog)
        assert secret not in diagnostics
    for secret in (vapid_private, GOOD_SUBSCRIPTION["endpoint"], GOOD_SUBSCRIPTION["keys"]["auth"]):
        assert secret not in diagnostics and secret not in _logged(caplog)
    assert json.loads(diagnostics)["guests"]["push_subscriptions"] == 1


# ----- the page ------------------------------------------------------------------------


async def test_the_web_app_is_installable_and_locked_down(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any
) -> None:
    await _invite(hass, hass_ws_client)
    page = await client.get("/api/family_hub/guest/", headers={"Origin": "https://evil.example"})
    assert page.status == 200
    for header, value in (
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "no-referrer"),
    ):
        assert page.headers[header] == value
    csp = page.headers["Content-Security-Policy"]
    assert "default-src 'none'" in csp and "script-src 'self'" in csp
    assert "unsafe-inline" not in csp
    assert "Access-Control-Allow-Origin" not in page.headers
    html = await page.text()
    assert "<script>" not in html and 'rel="apple-touch-icon"' in html
    # The manifest is added by the page's script, except on iPhone (see app.js).
    script = await (await client.get("/api/family_hub/guest/app.js")).text()
    assert 'link.rel = "manifest"' in script
    # Opened from the iPhone's Home Screen icon: ?i= in the address. Served, never stored.
    with_invite = await client.get("/api/family_hub/guest/?i=" + "x" * 43)
    assert with_invite.status == 200
    assert with_invite.headers["Cache-Control"] == "no-store"
    manifest = await (await client.get("/api/family_hub/guest/manifest.json")).json()
    assert manifest["name"] == "Family Hub" and manifest["display"] == "standalone"
    assert manifest["scope"] == "/api/family_hub/guest/"
    sizes = {(i["sizes"], i.get("purpose", "any")) for i in manifest["icons"]}
    assert {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= sizes
    for icon in manifest["icons"]:
        answer = await client.get(icon["src"])
        assert answer.status == 200 and answer.headers["Content-Type"] == "image/png"
    worker = await client.get("/api/family_hub/guest/sw.js")
    assert worker.status == 200
    assert worker.headers["Content-Type"].startswith("text/javascript")
    assert worker.headers["Service-Worker-Allowed"] == "/api/family_hub/guest/"
    assert (await client.get("/api/family_hub/guest/../manifest.json")).status == 404
    assert (await client.get("/api/family_hub/guest/guests.py")).status == 404
    api = await client.options(
        f"{API}me",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "Access-Control-Allow-Origin" not in api.headers


async def test_the_invite_link_uses_the_external_address(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any
) -> None:
    await hass.config.async_update(external_url="https://casa.example.org")
    answer = await _ws(
        hass,
        hass_ws_client,
        "invite_create",
        invite={"name": GRANDMA, "persons": ["sofia"], "categories": ["scuola"]},
    )
    assert answer["result"]["link"].startswith("https://casa.example.org/api/family_hub/guest/#i=")
    assert answer["result"]["external_url"] is True
    assert (await _ws(hass, hass_ws_client, "list"))["result"]["external_url"] is True


# ----- notifications ---------------------------------------------------------------------


async def test_push_subscriptions_must_be_real_push_services(
    hass: HomeAssistant, client: TestClient, hass_ws_client: Any, family: MockConfigEntry
) -> None:
    device_id, token = await _device(hass, client, hass_ws_client)
    _unlimited(hass)
    for endpoint in (
        "http://fcm.googleapis.com/x",
        "https://192.168.1.10/push",
        "https://homeassistant.local:8123/api/states",
        "https://fcm.googleapis.com.evil.example/x",
        "https://user:pw@fcm.googleapis.com/x",
    ):
        bad = {**GOOD_SUBSCRIPTION, "endpoint": endpoint}
        answer = await client.post(f"{API}push", json={"subscription": bad}, headers=_auth(token))
        assert answer.status == 422, endpoint
    answer = await client.post(
        f"{API}push", json={"subscription": GOOD_SUBSCRIPTION}, headers=_auth(token)
    )
    assert await answer.json() == {"push": True}
    assert family.runtime_data.guests.devices[device_id]["push"] == GOOD_SUBSCRIPTION
    assert await (await client.delete(f"{API}push", headers=_auth(token))).json() == {"push": False}


async def test_the_access_log_never_shows_an_invite(
    hass: HomeAssistant,
    client: TestClient,
    hass_ws_client: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Home Assistant keeps aiohttp's access log off; if someone turns it on, the invite in a
    guest address (?i=, from the iPhone icon) is still hidden."""
    _, token = await _invite(hass, hass_ws_client)
    access = logging.getLogger("aiohttp.access")
    caplog.set_level(logging.INFO, logger="aiohttp.access")
    access.info(f'127.0.0.1 "GET /api/family_hub/guest/?i={token} HTTP/1.1" 200 1234')
    access.info('127.0.0.1 "GET /api/states?i=keepme HTTP/1.1" 200 12')
    text = " | ".join(r.getMessage() for r in caplog.records if r.name == "aiohttp.access")
    assert token not in text and "/api/family_hub/guest/?i=***" in text
    assert "keepme" in text  # other addresses are left alone


def test_subscriptions_of_the_browsers_are_accepted() -> None:
    for host in (
        "fcm.googleapis.com",
        "web.push.apple.com",
        "updates.push.services.mozilla.com",
        "wns2-par02p.notify.windows.com",
    ):
        assert webpush.clean_subscription({**GOOD_SUBSCRIPTION, "endpoint": f"https://{host}/x"})
    assert webpush.clean_subscription({"endpoint": "https://fcm.googleapis.com/x"}) is None
    keys = {"p256dh": "short", "auth": "c2VjcmV0"}
    assert webpush.clean_subscription({**GOOD_SUBSCRIPTION, "keys": keys}) is None


async def test_guests_get_reminders_and_changes_of_what_they_see(
    hass: HomeAssistant,
    client: TestClient,
    hass_ws_client: Any,
    family: MockConfigEntry,
    no_real_push: Any,
) -> None:
    device_id, _ = await _device(hass, client, hass_ws_client)
    family.runtime_data.guests.devices[device_id]["push"] = GOOD_SUBSCRIPTION
    await _family_event(hass, "scuola", ["sofia"], "Recita di Sofia")
    await _family_event(hass, "lavoro", ["mamma"], "Cena di lavoro")
    store = family.runtime_data.store
    uids = {r["summary"]: uid for uid, r in store.events.items()}
    reminders = family.runtime_data.reminders
    # A reminder at the family's moment, outside quiet hours.
    with patch.object(guests_module.GuestManager, "_quiet_now", return_value=False):
        for name in ("Recita di Sofia", "Cena di lavoro"):
            await reminders.async_fire(uids[name], dt_util.utcnow())
        await hass.async_block_till_done()
    bodies = [call.args[2]["body"] for call in no_real_push.call_args_list]
    assert any("Recita di Sofia" in b for b in bodies)
    assert not any("Cena di lavoro" in b for b in bodies)
    no_real_push.reset_mock()
    # Quiet hours: nothing.
    store.events[uids["Recita di Sofia"]]["sent"] = []
    with patch.object(guests_module.GuestManager, "_quiet_now", return_value=True):
        await reminders.async_fire(uids["Recita di Sofia"], dt_util.utcnow() + timedelta(minutes=1))
        await hass.async_block_till_done()
    assert no_real_push.call_count == 0
    # A change and a cancellation of a visible appointment; nothing for the hidden one.
    await hass.services.async_call(
        DOMAIN,
        "update_event",
        {
            "uid": uids["Recita di Sofia"],
            "start": f"{_day(4)} 09:00:00",
            "end": f"{_day(4)} 10:00:00",
        },
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN, "delete_event", {"uid": uids["Cena di lavoro"]}, blocking=True
    )
    await hass.services.async_call(
        DOMAIN, "delete_event", {"uid": uids["Recita di Sofia"]}, blocking=True
    )
    await hass.async_block_till_done()
    bodies = [call.args[2]["body"] for call in no_real_push.call_args_list]
    assert any(b.startswith("Modificato: Recita di Sofia") for b in bodies)
    assert any(b.startswith("Annullato: Recita di Sofia") for b in bodies)
    assert not any("Cena" in b for b in bodies)


async def test_a_gone_subscription_is_forgotten(
    hass: HomeAssistant,
    client: TestClient,
    hass_ws_client: Any,
    family: MockConfigEntry,
    no_real_push: Any,
) -> None:
    device_id, _ = await _device(hass, client, hass_ws_client)
    device = family.runtime_data.guests.devices[device_id]
    device["push"] = GOOD_SUBSCRIPTION
    no_real_push.return_value = webpush.GONE
    await family.runtime_data.guests._push(device, {"title": "x", "body": "y"})
    assert device["push"] is None


# ----- small parts ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("agent", "label"),
    [
        (ANDROID, "Android · Chrome"),
        (IPHONE, "iPhone · Safari"),
        (
            "Mozilla/5.0 (Linux; Android 13) SamsungBrowser/25.0 Chrome/121",
            "Android · Samsung Internet",
        ),
        ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) CriOS/120.0 Mobile Safari", "iPhone · Chrome"),
        ("", "? · Browser"),
    ],
)
def test_devices_are_described_from_their_browser(agent: str, label: str) -> None:
    assert describe_device(agent) == label


async def test_clean_event_keeps_the_local_time(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Europe/Rome")
    today = dt_util.now().date()
    event = clean_event(_new(date=today.isoformat()), ["sofia"], ["scuola"], today)
    assert event["start"].startswith(f"{today.isoformat()}T16:00:00")
    assert event["persons"] == ["sofia"] and event["description"] == "Porto i biscotti"
