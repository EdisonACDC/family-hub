"""Invites, 0.9.0b7: appointments of the whole family (no person) for guests who may see them,
and notifications of new appointments to the guests' phones."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import patch

from aiohttp.test_utils import TestClient
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from test_guests import (  # noqa: F401 - the fixtures are used by name
    API,
    GOOD_SUBSCRIPTION,
    _auth,
    _day,
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


async def _add(
    hass: HomeAssistant, summary: str, persons: list[str], days: int = 3, category: str = "scuola"
) -> None:
    await hass.services.async_call(
        "family_hub",
        "add_event",
        {
            "category": category,
            "summary": summary,
            "persons": persons,
            "start": f"{_day(days)} 07:00:00",
            "end": f"{_day(days)} 08:00:00",
        },
        blocking=True,
    )


def _uid(entry: MockConfigEntry, summary: str) -> str:
    return next(u for u, r in entry.runtime_data.store.events.items() if r["summary"] == summary)


# ----- 3: appointments of the whole family ------------------------------------------------


async def test_family_appointments_only_when_allowed(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
) -> None:
    device_id, token = await _device(hass, client, hass_ws_client)
    await _add(hass, "PEDIATRA", [])
    await _add(hass, "Riunione di Mamma", ["mamma"])
    await _add(hass, "Visita in un altro calendario", [], category="lavoro")
    titles = [e["title"] for e in (await (await _list(client, token)).json())["events"]]
    assert titles == []  # off by default
    answer = await _ws(
        hass, hass_ws_client, "device_update", device_id=device_id, changes={"family_events": True}
    )
    assert answer["success"]
    events = (await (await _list(client, token)).json())["events"]
    assert [(e["title"], e["persons"]) for e in events] == [("PEDIATRA", [])]
    bad = await _ws(
        hass, hass_ws_client, "device_update", device_id=device_id, changes={"family_events": "si"}
    )
    assert not bad["success"]


async def test_the_invite_carries_the_family_option(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    device_id, _ = await _device(hass, client, hass_ws_client, family_events=True)
    assert _manager(family).devices[device_id]["family_events"] is True
    listed = (await _ws(hass, hass_ws_client, "list"))["result"]
    assert listed["devices"][0]["family_events"] is True
    assert listed["invites"][0]["family_events"] is True


# ----- 5: new appointments --------------------------------------------------------------


async def _listening_device(hass: HomeAssistant, http: TestClient, ws: Any, **kw: Any) -> Any:
    device_id, token = await _device(hass, http, ws, **kw)
    await http.post(f"{API}push", json={"subscription": GOOD_SUBSCRIPTION}, headers=_auth(token))
    return device_id, token


def _later(hass: HomeAssistant, minutes: int = 3) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=minutes))


async def test_a_new_appointment_reaches_the_guest(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
    no_real_push: Any,  # noqa: F811
) -> None:
    await _listening_device(hass, client, hass_ws_client)
    no_real_push.reset_mock()
    with patch.object(type(_manager(family)), "_quiet_for", return_value=False):
        await _add(hass, "PEDIATRA", ["sofia"], days=1)
        await _add(hass, "Cena di Mamma", ["mamma"], days=1)  # not hers to see
        await hass.async_block_till_done()
        assert no_real_push.call_count == 0  # collected for a moment first
        _later(hass)
        await hass.async_block_till_done()
    (call,) = no_real_push.call_args_list
    payload = call.args[2]
    uid = _uid(family, "PEDIATRA")
    start = dt_util.parse_datetime(family.runtime_data.store.events[uid]["start"])
    day = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"][dt_util.as_local(start).weekday()]
    expected = f"Nuovo impegno per Sofia: PEDIATRA, {day} {dt_util.as_local(start):%d/%m} ore 07:00"
    assert payload["body"] == expected
    assert payload["open"] == uid and payload["day"] == _day(1)


async def test_several_new_appointments_are_one_message(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
    no_real_push: Any,  # noqa: F811
) -> None:
    await _listening_device(hass, client, hass_ws_client)
    no_real_push.reset_mock()
    with patch.object(type(_manager(family)), "_quiet_for", return_value=False):
        for n in range(3):
            await _add(hass, f"Recita {n}", ["sofia"], days=2 + n)
        _later(hass)
        await hass.async_block_till_done()
    (call,) = no_real_push.call_args_list
    assert call.args[2]["body"] == "3 nuovi impegni per Sofia"


async def test_an_appointment_that_becomes_visible_is_new(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
    no_real_push: Any,  # noqa: F811
) -> None:
    await _add(hass, "PEDIATRA", [])
    await _listening_device(hass, client, hass_ws_client)
    no_real_push.reset_mock()
    with patch.object(type(_manager(family)), "_quiet_for", return_value=False):
        await hass.services.async_call(
            "family_hub",
            "update_event",
            {"uid": _uid(family, "PEDIATRA"), "persons": ["sofia"]},
            blocking=True,
        )
        _later(hass)
        await hass.async_block_till_done()
    bodies = [c.args[2]["body"] for c in no_real_push.call_args_list]
    assert len(bodies) == 1 and bodies[0].startswith("Nuovo impegno per Sofia: PEDIATRA")


async def test_no_message_for_own_appointments_or_when_switched_off(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
    no_real_push: Any,  # noqa: F811
) -> None:
    device_id, token = await _listening_device(hass, client, hass_ws_client, approval="direct")
    _unlimited(hass)
    no_real_push.reset_mock()
    with patch.object(type(_manager(family)), "_quiet_for", return_value=False):
        await client.post(f"{API}events", json=_new(), headers=_auth(token))
        _later(hass)
        await hass.async_block_till_done()
        assert no_real_push.call_count == 0
        await _ws(
            hass,
            hass_ws_client,
            "device_update",
            device_id=device_id,
            changes={"notify_new": False},
        )
        await _add(hass, "PEDIATRA", ["sofia"])
        _later(hass, 6)
        await hass.async_block_till_done()
    assert no_real_push.call_count == 0
    listed = (await _ws(hass, hass_ws_client, "list"))["result"]
    assert listed["devices"][0]["notify_new"] is False


async def test_during_quiet_hours_the_message_waits_for_their_end(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
    no_real_push: Any,  # noqa: F811
) -> None:
    manager = _manager(family)
    device_id, _ = await _listening_device(hass, client, hass_ws_client)
    no_real_push.reset_mock()
    with patch.object(type(manager), "_quiet_for", return_value=True):
        await _add(hass, "PEDIATRA", ["sofia"])
        _later(hass)
        await hass.async_block_till_done()
    assert no_real_push.call_count == 0
    assert device_id in manager._new_timers  # waiting for the end of the quiet hours
    end = manager._quiet_end(manager.devices[device_id])
    with patch.object(type(manager), "_quiet_for", return_value=False):
        async_fire_time_changed(hass, end + timedelta(seconds=1))
        await hass.async_block_till_done()
    (call,) = no_real_push.call_args_list
    assert call.args[2]["body"].startswith("Nuovo impegno per Sofia: PEDIATRA")
