"""Invites, 0.9.0b6: requests answered once go from the other phones, reminders open their event,
and each guest phone has its own reminders, quiet hours, status and test notification."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from test_guests import (  # noqa: F401 - the fixtures are used by name
    API,
    GOOD_SUBSCRIPTION,
    _activate,
    _auth,
    _device,
    _invite,
    _manager,
    _unlimited,
    _ws,
    client,
    family,
    fresh_limits,
    no_real_push,
)

PANEL = "/app/abcd1234_family_hub_ui"


async def test_an_answered_request_goes_from_the_other_phones(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    hass_admin_user: Any,
) -> None:
    calls: dict[str, list[Any]] = {}
    for name in ("Telefono Uno", "Telefono Due"):
        MockConfigEntry(
            domain="mobile_app", data={"user_id": hass_admin_user.id, "device_name": name}
        ).add_to_hass(hass)
        service = slugify(f"mobile_app_{name}")
        calls[service] = []
        hass.services.async_register("notify", service, calls[service].append)
    _, invite_token = await _invite(hass, hass_ws_client)
    await _activate(client, invite_token)
    await hass.async_block_till_done()
    device_id = (await _ws(hass, hass_ws_client, "list"))["result"]["devices"][0]["id"]
    # Confirmed on one phone: the request is cleared on both (same tag).
    action = calls["mobile_app_telefono_uno"][0].data["data"]["actions"][0]["action"]
    hass.bus.async_fire("mobile_app_notification_action", {"action": action})
    await hass.async_block_till_done()
    for service_calls in calls.values():
        last = service_calls[-1].data
        assert last["message"] == "clear_notification"
        assert last["data"]["tag"] == f"family_hub_guest_{device_id}"


async def test_answered_on_the_tablet_the_only_phone_is_cleared_too(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    calls: list[Any] = []
    hass.services.async_register("notify", "mobile_app_telefono_mamma", calls.append)
    device_id, _ = await _device(hass, client, hass_ws_client)  # confirmed over the websocket
    await hass.async_block_till_done()
    assert calls[-1].data["message"] == "clear_notification"
    assert calls[-1].data["data"]["tag"] == f"family_hub_guest_{device_id}"


@pytest.fixture
def clock_at_noon(freezer: Any) -> None:
    # Noon in the test's time zone: outside the family's quiet hours (22:00 to 07:00).
    freezer.move_to("2026-11-23 12:00:00-08:00")


async def test_a_reminder_opens_its_event(
    clock_at_noon: None,
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    calls: list[Any] = []
    hass.services.async_register("notify", "mobile_app_telefono_mamma", calls.append)
    await _invite(hass, hass_ws_client)
    await _ws(hass, hass_ws_client, "panel", path=PANEL)
    start = dt_util.now() + timedelta(hours=3)
    await hass.services.async_call(
        "family_hub",
        "add_event",
        {
            "category": "scuola",
            "summary": "Colloquio",
            "persons": ["mamma"],
            "start": start.strftime("%Y-%m-%d %H:%M:00"),
            "end": (start + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:00"),
        },
        blocking=True,
    )
    (uid,) = family.runtime_data.store.events
    await family.runtime_data.reminders.async_fire(uid, dt_util.utcnow())
    data = calls[-1].data["data"]
    expected = f"{PANEL}?fh_open=event.{uid}.{start.date().isoformat()}"
    assert data["url"] == data["clickAction"] == expected
    assert data["tag"] == f"family_hub_{uid}"
    assert [a["title"] for a in data["actions"]][:2] == ["Fatto", "Ferma"]


async def test_each_phone_has_its_own_reminders_status_and_test(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
    no_real_push: Any,  # noqa: F811
) -> None:
    device_id, token = await _device(hass, client, hass_ws_client)
    _unlimited(hass)

    async def device() -> dict[str, Any]:
        listed = (await _ws(hass, hass_ws_client, "list"))["result"]["devices"]
        return next(d for d in listed if d["id"] == device_id)

    assert (await device())["push_status"] == "off"
    for bad in (
        {"reminder_offsets": []},
        {"reminder_offsets": [2000]},
        {"reminder_offsets": [1, 2, 3, 4, 5, 6]},
        {"quiet_start": "22:00"},
        {"quiet_start": "25:00", "quiet_end": "07:00"},
    ):
        answer = await _ws(hass, hass_ws_client, "device_update", device_id=device_id, changes=bad)
        assert not answer["success"], bad
    answer = await _ws(
        hass,
        hass_ws_client,
        "device_update",
        device_id=device_id,
        changes={"reminder_offsets": [15, 60], "quiet_start": "21:00", "quiet_end": "08:00"},
    )
    assert answer["success"]
    shown = await device()
    assert shown["reminder_offsets"] == [60, 15]
    assert (shown["quiet_start"], shown["quiet_end"]) == ("21:00", "08:00")
    # Back to the family's own.
    answer = await _ws(
        hass,
        hass_ws_client,
        "device_update",
        device_id=device_id,
        changes={"reminder_offsets": None, "quiet_start": "", "quiet_end": ""},
    )
    shown = await device()
    assert shown["reminder_offsets"] is None and shown["quiet_start"] is None
    # The test notification needs notifications on the phone.
    answer = await _ws(hass, hass_ws_client, "device_test_push", device_id=device_id)
    assert answer["error"]["code"] == "no_push"
    # The phone says its notifications are blocked: the adults see it.
    await client.post(f"{API}push", json={"blocked": True}, headers=_auth(token))
    assert (await device())["push_status"] == "blocked"
    await client.post(f"{API}push", json={"subscription": GOOD_SUBSCRIPTION}, headers=_auth(token))
    assert (await device())["push_status"] == "active"
    no_real_push.reset_mock()
    assert (await _ws(hass, hass_ws_client, "device_test_push", device_id=device_id))["success"]
    assert no_real_push.call_args.args[2]["tag"] == "test"
    # At most one a minute.
    answer = await _ws(hass, hass_ws_client, "device_test_push", device_id=device_id)
    assert answer["error"]["code"] == "slow_down"
    assert no_real_push.call_count == 1


async def test_a_phone_with_its_own_minutes_gets_them(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
    no_real_push: Any,  # noqa: F811
) -> None:
    device_id, token = await _device(hass, client, hass_ws_client)
    await client.post(f"{API}push", json={"subscription": GOOD_SUBSCRIPTION}, headers=_auth(token))
    await _ws(
        hass,
        hass_ws_client,
        "device_update",
        device_id=device_id,
        changes={"reminder_offsets": [90]},
    )
    manager = _manager(family)
    start = (dt_util.now() + timedelta(hours=2)).replace(second=0, microsecond=0)
    await hass.services.async_call(
        "family_hub",
        "add_event",
        {
            "category": "scuola",
            "summary": "Recita lunga",
            "persons": ["sofia"],
            "start": start.strftime("%Y-%m-%d %H:%M:00"),
            "end": (start + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:00"),
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    (uid,) = family.runtime_data.store.events
    assert any(key[1] == uid for key in manager._own_timers)
    no_real_push.reset_mock()
    # The family's reminder of a timed appointment is not sent to this phone: it has its own.
    with patch.object(type(manager), "_quiet_for", return_value=False):
        await manager.async_on_reminder(family.runtime_data.store.events[uid], "x · Recita lunga")
        await hass.async_block_till_done()
        assert no_real_push.call_count == 0
        # Its own reminder, 90 minutes before.
        async_fire_time_changed(hass, dt_util.as_utc(start - timedelta(minutes=90)))
        await hass.async_block_till_done()
    # (The "new appointment" message is a different one, with its own tag.)
    reminders = [c for c in no_real_push.call_args_list if c.args[2].get("tag") == uid]
    (call,) = reminders
    assert call.args[2]["body"].endswith("· Recita lunga")
