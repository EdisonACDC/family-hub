# ruff: noqa: F811 - the fixtures are used by name, as in the other guest tests
"""Guest web app, 0.11.0b1: chosen dates. A guest with the permission to add appointments makes one
event on dates it picks, each with its own times; every date is marked with the guest; the adults
confirm the whole series; a guest changes or deletes "this", "this and the following" or "all" of
its own series; a guest without the permission is refused; a private series is never shown."""

from __future__ import annotations

from typing import Any

from aiohttp.test_utils import TestClient
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_guests import (  # noqa: F401 - the fixtures are used by name
    API,
    _activate,
    _auth,
    _day,
    _device,
    _invite,
    _manager,
    _ws,
    client,
    family,
    fresh_limits,
    no_real_push,
)

from custom_components.family_hub.const import DOMAIN


def _chosen(**overrides: Any) -> dict[str, Any]:
    return {
        "title": "Recita di Natale",
        "person": "sofia",
        "category": "scuola",
        "dates": [
            {"date": _day(2), "start": "16:00", "end": "17:30"},
            {"date": _day(30), "start": "10:00", "end": "11:00"},
        ],
        "location": "Teatro",
        "note": "Costume bianco",
        **overrides,
    }


def _series(hass: HomeAssistant) -> list[dict[str, Any]]:
    family_entry = hass.config_entries.async_entries(DOMAIN)[0]
    return sorted(
        (r for r in family_entry.runtime_data.store.events.values() if r.get("chosen")),
        key=lambda r: r["start"],
    )


async def _post(client: TestClient, token: str, body: dict[str, Any]) -> Any:
    return await client.post(f"{API}events", json=body, headers=_auth(token))


async def test_a_guest_makes_a_series_with_its_own_times_marked_with_the_guest(
    hass: HomeAssistant,
    client: TestClient,
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    device_id, token = await _device(hass, client, hass_ws_client, approval="direct")
    answer = await _post(client, token, _chosen())
    assert answer.status == 201, await answer.text()
    records = _series(hass)
    assert [r["start"][11:16] for r in records] == ["16:00", "10:00"]
    assert [r["end"][11:16] for r in records] == ["17:30", "11:00"]
    assert len({r["series"] for r in records}) == 1
    assert all(r["rrule"] == "" and r["complete"] for r in records)
    assert all(r["added_by"]["device"] == device_id for r in records)


async def test_a_guest_without_the_permission_is_refused(
    hass: HomeAssistant,
    client: TestClient,
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    _, token = await _device(hass, client, hass_ws_client, permission="view")
    answer = await _post(client, token, _chosen())
    assert answer.status == 403
    assert _series(hass) == []


async def test_dates_with_a_rule_or_a_bad_row_are_refused(
    hass: HomeAssistant,
    client: TestClient,
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    _, token = await _device(hass, client, hass_ws_client, approval="direct")
    assert (await _post(client, token, _chosen(rrule="FREQ=DAILY"))).status == 422
    backwards = _chosen()
    backwards["dates"][1]["end"] = "09:00"
    assert (await _post(client, token, backwards)).status == 422
    too_many = _chosen()
    too_many["dates"] = [{"date": _day(i), "start": "10:00", "end": "11:00"} for i in range(51)]
    assert (await _post(client, token, too_many)).status == 422
    assert _series(hass) == []


async def test_the_adults_confirm_the_whole_series(
    hass: HomeAssistant,
    client: TestClient,
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    _, token = await _device(hass, client, hass_ws_client)
    answer = await _post(client, token, _chosen())
    assert answer.status == 201
    assert _series(hass) == []
    manager = _manager(family)
    (item_id,) = list(manager.pending)
    assert len(manager.pending[item_id]["event"]["dates"]) == 2
    await manager.async_approve(item_id, True)
    await hass.async_block_till_done()
    assert [r["start"][11:16] for r in _series(hass)] == ["16:00", "10:00"]


async def test_all_changes_the_title_and_keeps_each_time(
    hass: HomeAssistant,
    client: TestClient,
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    _, token = await _device(hass, client, hass_ws_client, approval="direct")
    await _post(client, token, _chosen())
    first = _series(hass)[0]["uid"]
    change = {
        "title": "Concerto di Natale",
        "person": "sofia",
        "category": "scuola",
        "dates": [
            {"date": _day(2), "start": "16:00", "end": "17:30"},
            {"date": _day(30), "start": "10:00", "end": "11:00"},
        ],
        "scope": "ALL",
    }
    answer = await client.put(f"{API}events/{first}", json=change, headers=_auth(token))
    assert answer.status == 200, await answer.text()
    records = _series(hass)
    assert [r["summary"] for r in records] == ["Concerto di Natale", "Concerto di Natale"]
    assert [r["start"][11:16] for r in records] == ["16:00", "10:00"]


async def test_this_and_the_following_deletes_the_later_dates(
    hass: HomeAssistant,
    client: TestClient,
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    _, token = await _device(hass, client, hass_ws_client, approval="direct")
    await _post(
        client,
        token,
        _chosen(
            dates=[
                {"date": _day(2), "start": "16:00", "end": "17:30"},
                {"date": _day(10), "start": "16:00", "end": "17:30"},
                {"date": _day(30), "start": "10:00", "end": "11:00"},
            ]
        ),
    )
    second = _series(hass)[1]["uid"]
    answer = await client.delete(f"{API}events/{second}?scope=THISANDFUTURE", headers=_auth(token))
    assert answer.status == 200, await answer.text()
    assert len(_series(hass)) == 1


async def test_this_only_deletes_one_date(
    hass: HomeAssistant,
    client: TestClient,
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    _, token = await _device(hass, client, hass_ws_client, approval="direct")
    await _post(client, token, _chosen())
    first = _series(hass)[0]["uid"]
    answer = await client.delete(f"{API}events/{first}", headers=_auth(token))
    assert answer.status == 200
    assert len(_series(hass)) == 1


async def test_all_deletes_the_whole_series(
    hass: HomeAssistant,
    client: TestClient,
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    _, token = await _device(hass, client, hass_ws_client, approval="direct")
    await _post(client, token, _chosen())
    first = _series(hass)[0]["uid"]
    answer = await client.delete(f"{API}events/{first}?scope=ALL", headers=_auth(token))
    assert answer.status == 200
    assert _series(hass) == []


async def test_a_series_of_the_family_is_not_changed_by_a_guest(
    hass: HomeAssistant,
    client: TestClient,
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    _, token = await _device(hass, client, hass_ws_client, approval="direct")
    family_series = await hass.services.async_call(
        DOMAIN,
        "add_event",
        {
            "category": "scuola",
            "summary": "Riunione",
            "start": f"{_day(3)} 18:00:00",
            "end": f"{_day(3)} 19:00:00",
            "persons": ["sofia"],
            "dates": [
                {"start": f"{_day(3)} 18:00:00", "end": f"{_day(3)} 19:00:00"},
                {"start": f"{_day(9)} 18:00:00", "end": f"{_day(9)} 19:00:00"},
            ],
        },
        blocking=True,
        return_response=False,
    )
    assert family_series is None
    other = _series(hass)[0]["uid"]
    answer = await client.delete(f"{API}events/{other}?scope=ALL", headers=_auth(token))
    assert answer.status in (403, 404)
    assert len(_series(hass)) == 2


async def test_a_private_series_is_never_shown_to_a_guest(
    hass: HomeAssistant,
    client: TestClient,
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    _, token = await _device(hass, client, hass_ws_client)
    await hass.services.async_call(
        DOMAIN,
        "add_event",
        {
            "category": "scuola",
            "summary": "Colloquio segreto",
            "start": f"{_day(2)} 09:00:00",
            "end": f"{_day(2)} 10:00:00",
            "persons": ["sofia"],
            "private": True,
            "dates": [
                {"start": f"{_day(2)} 09:00:00", "end": f"{_day(2)} 10:00:00"},
                {"start": f"{_day(9)} 09:00:00", "end": f"{_day(9)} 10:00:00"},
            ],
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    listed = await client.get(
        f"{API}events", params={"from": _day(0), "days": "40"}, headers=_auth(token)
    )
    titles = [item["title"] for item in (await listed.json())["events"]]
    assert "Colloquio segreto" not in titles


async def test_the_adults_list_every_date_waiting_and_a_change_keeps_them(
    hass: HomeAssistant,
    client: TestClient,
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    _, token = await _device(hass, client, hass_ws_client)
    await _post(client, token, _chosen())
    listed = await _ws(hass, hass_ws_client, "list")
    (waiting,) = listed["result"]["pending"]
    assert [d["start"][11:16] for d in waiting["dates"]] == ["16:00", "10:00"]
    manager = _manager(family)
    (item_id,) = list(manager.pending)
    changes = {
        "title": "Concerto di Natale",
        "person": "sofia",
        "category": "scuola",
        "date": _day(2),
        "all_day": False,
        "start": "09:00",
        "end": "10:00",
    }
    await manager.async_approve(item_id, True, changes=changes)
    await hass.async_block_till_done()
    records = _series(hass)
    assert [r["summary"] for r in records] == ["Concerto di Natale", "Concerto di Natale"]
    assert [r["start"][11:16] for r in records] == ["16:00", "10:00"]
