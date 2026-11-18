"""0.10.3: simultaneous changes. An appointment has a version; a change (update or delete) from a
service, the panel or the guests' web app sends the version it read, and when the appointment is
different by then it is refused ("event_changed"), never silently overwritten. A change with no
version (an automation, an older phone) works as before. Names are invented."""

from __future__ import annotations

from typing import Any

import pytest
from aiohttp.test_utils import TestClient
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_guests import (  # noqa: F401 - the fixtures are used by name
    API,
    _auth,
    _day,
    _device,
    _unlimited,
    client,  # noqa: F811
    family,  # noqa: F811
    fresh_limits,
    no_real_push,
)

from custom_components.family_hub.const import DOMAIN
from custom_components.family_hub.services import _calendar_for
from custom_components.family_hub.storage import event_version


@pytest.fixture
def expected_lingering_timers() -> bool:
    return True


async def _add(hass: HomeAssistant, summary: str = "Dal pediatra") -> str:
    await hass.services.async_call(
        DOMAIN,
        "add_event",
        {
            "category": "scuola",
            "summary": summary,
            "persons": ["sofia"],
            "start": f"{_day(2)} 10:00:00",
            "end": f"{_day(2)} 11:00:00",
        },
        blocking=True,
    )
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    return next(
        r["uid"] for r in entry.runtime_data.store.events.values() if r["summary"] == summary
    )


def _record(hass: HomeAssistant, uid: str) -> dict[str, Any]:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    return entry.runtime_data.store.events[uid]


async def test_the_version_follows_what_a_person_can_change(
    hass: HomeAssistant,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    uid = await _add(hass)
    record = _record(hass, uid)
    first = event_version(record)
    assert len(first) == 12
    # The panel's events carry it.
    event = _calendar_for(family, "scuola")._to_calendar_event(record)
    assert event.version == first  # type: ignore[attr-defined]
    # A reminder that is stopped or snoozed is not a change someone made.
    record["reminders_off"] = True
    assert event_version(record) == first
    # A change of the appointment is.
    await hass.services.async_call(
        DOMAIN, "update_event", {"uid": uid, "summary": "Dal dentista"}, blocking=True
    )
    assert event_version(record) != first


async def test_services_refuse_a_change_on_an_old_version(
    hass: HomeAssistant,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    uid = await _add(hass)
    read = event_version(_record(hass, uid))
    # Someone else changes it first.
    await hass.services.async_call(
        DOMAIN, "update_event", {"uid": uid, "summary": "Cambiato da altri"}, blocking=True
    )
    for service, data in (
        ("update_event", {"summary": "La mia modifica"}),
        ("delete_event", {}),
        ("move_event", {"start": f"{_day(3)} 10:00:00"}),
    ):
        with pytest.raises(ServiceValidationError, match="event_changed"):
            await hass.services.async_call(
                DOMAIN, service, {"uid": uid, "version": read, **data}, blocking=True
            )
    # Nothing was written.
    assert _record(hass, uid)["summary"] == "Cambiato da altri"
    assert _record(hass, uid)["start"].startswith(_day(2))
    # On the version that is now, the change works; the one it replaces is old at once.
    now = event_version(_record(hass, uid))
    await hass.services.async_call(
        DOMAIN, "update_event", {"uid": uid, "version": now, "summary": "Mia"}, blocking=True
    )
    assert _record(hass, uid)["summary"] == "Mia"
    with pytest.raises(ServiceValidationError, match="event_changed"):
        await hass.services.async_call(
            DOMAIN, "delete_event", {"uid": uid, "version": now}, blocking=True
        )
    # No version: as before.
    await hass.services.async_call(DOMAIN, "delete_event", {"uid": uid}, blocking=True)
    assert uid not in hass.config_entries.async_entries(DOMAIN)[0].runtime_data.store.events


async def _guest_event(http: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    body = {
        "title": "Merenda",
        "person": "sofia",
        "category": "scuola",
        "date": _day(2),
        "all_day": False,
        "start": "16:00",
        "end": "17:00",
    }
    answer = await http.post(f"{API}events", json=body, headers=headers)
    assert answer.status == 201, await answer.text()
    return (await answer.json())["event"]


async def test_a_guest_change_on_an_old_version_is_refused(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    _unlimited(hass)
    _, token = await _device(hass, client, hass_ws_client, approval="direct")
    headers = _auth(token)
    event = await _guest_event(client, headers)
    version = event["version"]
    listed = (
        await (await client.get(f"{API}events?from={_day(0)}&days=7", headers=headers)).json()
    )["events"]
    assert [e["version"] for e in listed if e["id"] == event["id"]] == [version]
    body = {
        "title": "Merenda",
        "person": "sofia",
        "category": "scuola",
        "date": _day(2),
        "all_day": False,
        "start": "16:00",
        "end": "17:30",
    }
    # An adult changes it meanwhile.
    await hass.services.async_call(
        DOMAIN, "update_event", {"uid": event["id"], "summary": "Merenda dai nonni"}, blocking=True
    )
    answer = await client.put(
        f"{API}events/{event['id']}", json={**body, "version": version}, headers=headers
    )
    assert answer.status == 409 and (await answer.json()) == {"error": "event_changed"}
    answer = await client.delete(f"{API}events/{event['id']}?version={version}", headers=headers)
    assert answer.status == 409 and (await answer.json()) == {"error": "event_changed"}
    assert _record(hass, event["id"])["summary"] == "Merenda dai nonni"
    # Reloaded: the new version works, and the answer carries the next one.
    listed = (
        await (await client.get(f"{API}events?from={_day(0)}&days=7", headers=headers)).json()
    )["events"]
    now = next(e["version"] for e in listed if e["id"] == event["id"])
    assert now != version
    answer = await client.put(
        f"{API}events/{event['id']}", json={**body, "version": now}, headers=headers
    )
    assert answer.status == 200
    newest = (await answer.json())["event"]["version"]
    assert newest not in (version, now)
    # An older phone sends no version: it works as before.
    answer = await client.put(f"{API}events/{event['id']}", json=body, headers=headers)
    assert answer.status == 200
    # A version that is not one is refused as a bad request, not as a conflict.
    answer = await client.put(
        f"{API}events/{event['id']}", json={**body, "version": "zz zz"}, headers=headers
    )
    assert answer.status == 422
    answer = await client.delete(f"{API}events/{event['id']}?version=nope!", headers=headers)
    assert answer.status == 422
    # Deleting on the current version works.
    current = (await answer_events(client, headers, event["id"]))["version"]
    answer = await client.delete(f"{API}events/{event['id']}?version={current}", headers=headers)
    assert answer.status == 200


async def answer_events(http: TestClient, headers: dict[str, str], item_id: str) -> dict[str, Any]:
    listed = (await (await http.get(f"{API}events?from={_day(0)}&days=7", headers=headers)).json())[
        "events"
    ]
    return next(e for e in listed if e["id"] == item_id)


async def test_days_over_the_most_give_the_most(
    hass: HomeAssistant,
    client: TestClient,  # noqa: F811
    hass_ws_client: Any,
    family: MockConfigEntry,  # noqa: F811
) -> None:
    """0.10.4: asking for more days than the most (62) gives the most, never an empty list and
    never more than the guest may see."""
    _unlimited(hass)
    _, token = await _device(hass, client, hass_ws_client)
    for summary, offset in (("Dentista vicino", 3), ("Gita lontana", 70)):
        await hass.services.async_call(
            DOMAIN,
            "add_event",
            {
                "category": "scuola",
                "summary": summary,
                "persons": ["sofia"],
                "start": f"{_day(offset)} 10:00:00",
                "end": f"{_day(offset)} 11:00:00",
            },
            blocking=True,
        )
    for days in (62, 63, 1000, 99999):
        answer = await client.get(f"{API}events?from={_day(0)}&days={days}", headers=_auth(token))
        assert answer.status == 200, days
        titles = [e["title"] for e in (await answer.json())["events"]]
        assert titles == ["Dentista vicino"], days
    # Not a number, or less than one: still a bad request.
    for days in ("0", "-3", "tanti"):
        answer = await client.get(f"{API}events?from={_day(0)}&days={days}", headers=_auth(token))
        assert answer.status == 422, days
