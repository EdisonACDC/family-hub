"""Rule zero: the adults' privacy. A guest who sees Sofia gets nothing of Mamma or Papà: not in the
web app's answers, not in notifications, not in reminders. Private appointments never reach a
guest, even with Sofia in them. Names are invented."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.family_hub import webpush
from custom_components.family_hub.const import (
    CONF_FAMILY_NAME,
    CONF_FIRST_WEEKDAY,
    CONF_LANGUAGE,
    DOMAIN,
    OPT_CATEGORIES,
    OPT_PERSONS,
)
from custom_components.family_hub.guests import RateLimiter, guest_hub

API = "/api/family_hub/guest/api/"
SUBSCRIPTION = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/abc123",
    "keys": {"p256dh": "B" + "A" * 86, "auth": "c2VjcmV0YXV0aDEyMzQ"},
}
PERSONS = [
    {"id": "sofia", "name": "Sofia", "color": "#FF8800", "role": "child"},
    {"id": "mamma", "name": "Mamma Riservata", "color": "#123456", "role": "adult"},
    {"id": "papa", "name": "Papà Riservato", "color": "#654321", "role": "adult"},
]
CATEGORIES = [{"id": "dottore", "name": "Dottore", "color": "#EF4444"}]
# What must never reach the guest.
SECRETS = (
    "Mamma",
    "Papà",
    "#123456",
    "#654321",
    "SOLO-MAMMA",
    "SOLO-PAPA",
    "SENZA-PERSONA",
    "PRIVATO-CON-SOFIA",
)


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
    hass.data.setdefault(DOMAIN, {})
    yield await hass_client_no_auth()


@pytest.fixture
def pushes() -> Any:
    with patch.object(webpush, "async_send", return_value=webpush.SENT) as send:
        yield send


def _day(offset: int) -> str:
    return (dt_util.now().date() + timedelta(days=offset)).isoformat()


async def _ws(ws_client: Any, command: str, **data: Any) -> dict[str, Any]:
    client = await ws_client()
    await client.send_json_auto_id({"type": f"family_hub/guest/{command}", **data})
    return await client.receive_json()


async def _sofia_phone(
    hass: HomeAssistant, client: TestClient, ws_client: Any, family_events: bool
) -> tuple[str, str]:
    """A grandmother's phone that sees Sofia in "Dottore", with notifications on."""
    hub = guest_hub(hass)
    hub.read_limit = RateLimiter(10_000)
    hub.write_limit = RateLimiter(10_000)
    created = await _ws(
        ws_client,
        "invite_create",
        invite={
            "name": "Nonna",
            "persons": ["sofia"],
            "categories": ["dottore"],
            "family_events": family_events,
        },
    )
    token = created["result"]["link"].split("#i=")[1]
    answer = await client.post(f"{API}activate", json={"token": token})
    device_token = (await answer.json())["token"]
    devices = (await _ws(ws_client, "list"))["result"]["devices"]
    await _ws(ws_client, "device_confirm", device_id=devices[0]["id"], accept=True)
    headers = {"Authorization": f"Bearer {device_token}"}
    await client.post(f"{API}push", json={"subscription": SUBSCRIPTION}, headers=headers)
    return devices[0]["id"], device_token


async def _add(
    hass: HomeAssistant, summary: str, persons: list[str], private: bool = False
) -> None:
    await hass.services.async_call(
        DOMAIN,
        "add_event",
        {
            "category": "dottore",
            "summary": summary,
            "persons": persons,
            "start": f"{_day(1)} 07:00:00",
            "end": f"{_day(1)} 08:00:00",
            "private": private,
        },
        blocking=True,
    )


def _uid(entry: MockConfigEntry, summary: str) -> str:
    return next(u for u, r in entry.runtime_data.store.events.items() if r["summary"] == summary)


@pytest.mark.parametrize("family_events", [False, True], ids=["default", "family_events_on"])
async def test_adults_appointments_never_reach_the_guest(
    hass: HomeAssistant,
    client: TestClient,
    hass_ws_client: Any,
    family: MockConfigEntry,
    pushes: Any,
    family_events: bool,
) -> None:
    _, token = await _sofia_phone(hass, client, hass_ws_client, family_events)
    pushes.reset_mock()
    manager = family.runtime_data.guests
    with patch.object(type(manager), "_quiet_for", return_value=False):
        await _add(hass, "SOLO-MAMMA", ["mamma"])
        await _add(hass, "SOLO-PAPA", ["papa"])
        await _add(hass, "SENZA-PERSONA", [])
        await _add(hass, "PRIVATO-CON-SOFIA", ["mamma", "sofia"], private=True)
        await _add(hass, "PEDIATRA", ["mamma", "sofia"])
        # Reminders of every appointment go out at the family's moment.
        for summary in (
            "SOLO-MAMMA",
            "SOLO-PAPA",
            "SENZA-PERSONA",
            "PRIVATO-CON-SOFIA",
            "PEDIATRA",
        ):
            await manager.async_on_reminder(
                family.runtime_data.store.events[_uid(family, summary)], f"07:00 · {summary}"
            )
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=5))
        await hass.async_block_till_done()
    # The web app's answer: only the shared appointment, with only Sofia.
    answer = await client.get(
        f"{API}events",
        params={"from": _day(0), "days": "14"},
        headers={"Authorization": f"Bearer {token}"},
    )
    body = await answer.json()
    expected = ["PEDIATRA", "SENZA-PERSONA"] if family_events else ["PEDIATRA"]
    assert sorted(e["title"] for e in body["events"]) == expected
    assert next(e for e in body["events"] if e["title"] == "PEDIATRA")["persons"] == ["sofia"]
    me = await (await client.get(f"{API}me", headers={"Authorization": f"Bearer {token}"})).json()
    text = json.dumps([body, me], ensure_ascii=False)
    for secret in SECRETS:
        if family_events and secret == "SENZA-PERSONA":
            continue
        assert secret not in text, secret
    # Notifications (new appointments and reminders): nothing of the adults, no private one.
    sent = json.dumps([c.args[2] for c in pushes.call_args_list], ensure_ascii=False)
    assert "PEDIATRA" in sent
    for secret in SECRETS:
        if family_events and secret == "SENZA-PERSONA":
            continue
        assert secret not in sent, secret


async def test_an_appointment_that_becomes_private_is_gone_at_once(
    hass: HomeAssistant,
    client: TestClient,
    hass_ws_client: Any,
    family: MockConfigEntry,
    pushes: Any,
) -> None:
    device_id, token = await _sofia_phone(hass, client, hass_ws_client, family_events=False)
    manager = family.runtime_data.guests
    await _ws(
        hass_ws_client, "device_update", device_id=device_id, changes={"reminder_offsets": [60]}
    )
    start = (dt_util.now() + timedelta(hours=3)).replace(second=0, microsecond=0)
    await hass.services.async_call(
        DOMAIN,
        "add_event",
        {
            "category": "dottore",
            "summary": "Visita",
            "persons": ["mamma", "sofia"],
            "start": start.strftime("%Y-%m-%d %H:%M:00"),
            "end": (start + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:00"),
        },
        blocking=True,
    )
    uid = _uid(family, "Visita")
    assert any(key[1] == uid for key in manager._own_timers)
    headers = {"Authorization": f"Bearer {token}"}
    params = {"from": _day(0), "days": "14"}

    async def titles() -> list[str]:
        answer = await client.get(f"{API}events", params=params, headers=headers)
        return [e["title"] for e in (await answer.json())["events"]]

    assert await titles() == ["Visita"]
    for change in ({"private": True}, {"persons": ["mamma"]}):
        await hass.services.async_call(
            DOMAIN, "update_event", {"uid": uid, **change}, blocking=True
        )
        assert await titles() == []
        # The reminder planned for this phone is cancelled at once.
        assert not any(key[1] == uid for key in manager._own_timers)
        await hass.services.async_call(
            DOMAIN,
            "update_event",
            {"uid": uid, "private": False, "persons": ["mamma", "sofia"]},
            blocking=True,
        )
        assert await titles() == ["Visita"]
    # Moved to a calendar the phone does not see: gone too.
    assert family.runtime_data.store.events[uid]["category"] == "dottore"
    pushes.reset_mock()
    with patch.object(type(manager), "_quiet_for", return_value=False):
        async_fire_time_changed(hass, dt_util.as_utc(start - timedelta(minutes=60)))
        await hass.async_block_till_done()
    assert all("Mamma" not in json.dumps(c.args[2]) for c in pushes.call_args_list)
