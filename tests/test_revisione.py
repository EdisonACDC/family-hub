"""Verifiche esterne (revisore): casi non coperti dai test originali."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.family_hub.const import (
    CONF_FAMILY_NAME,
    CONF_FIRST_WEEKDAY,
    CONF_LANGUAGE,
    DOMAIN,
    OPT_CATEGORIES,
    OPT_PERSONS,
)

CAL = "calendar.family_hub_famiglia"


async def _setup(
    hass: HomeAssistant, persons: list[dict[str, Any]] | None = None, reminders: dict | None = None
) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    opts: dict[str, Any] = {
        OPT_PERSONS: persons
        or [{"id": "sofia", "name": "Sofia", "color": "#FF8800", "role": "child"}],
        OPT_CATEGORIES: [{"id": "famiglia", "name": "Famiglia", "color": "#3B82F6"}],
    }
    if reminders is not None:
        opts["reminders"] = reminders
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "R", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
        options=opts,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _store(entry: MockConfigEntry) -> dict[str, Any]:
    return entry.runtime_data.store.events


async def test_A_standard_calendar_create_event(hass: HomeAssistant) -> None:
    """calendar.create_event (servizio standard di HA, usato da UI/automazioni)."""
    entry = await _setup(hass)
    await hass.services.async_call(
        "calendar",
        "create_event",
        {
            "entity_id": CAL,
            "summary": "Dentista",
            "start_date_time": "2027-01-10 15:00:00",
            "end_date_time": "2027-01-10 16:00:00",
        },
        blocking=True,
    )
    assert len(_store(entry)) == 1


async def test_B_ui_update_changes_time(hass: HomeAssistant, hass_ws_client: Any) -> None:
    """Modifica orario dall'interfaccia calendario di HA (websocket)."""
    entry = await _setup(hass)
    await hass.services.async_call(
        DOMAIN,
        "add_event",
        {
            "category": "famiglia",
            "summary": "X",
            "start": "2027-01-10 15:00",
            "end": "2027-01-10 16:00",
        },
        blocking=True,
    )
    uid = next(iter(_store(entry)))
    client = await hass_ws_client(hass)
    await client.send_json(
        {
            "id": 1,
            "type": "calendar/event/update",
            "entity_id": CAL,
            "uid": uid,
            "event": {
                "summary": "X",
                "dtstart": "2027-01-11T09:00:00+01:00",
                "dtend": "2027-01-11T10:00:00+01:00",
            },
        }
    )
    res = await client.receive_json()
    assert res["success"], res
    assert _store(entry)[uid]["start"].startswith("2027-01-11T09:00"), _store(entry)[uid]["start"]


async def _old_C(hass: HomeAssistant) -> None:
    """Un orario scritto male ('19.00') non deve bloccare promemoria né il riavvio."""
    entry = await _setup(hass)
    try:
        await hass.services.async_call(
            DOMAIN,
            "add_event",
            {
                "category": "famiglia",
                "summary": "Gita",
                "start": "2027-01-10",
                "all_day_reminder": "19.00",
            },
            blocking=True,
        )
    except Exception as err:  # rifiutato in ingresso: va bene
        if (
            "HH:MM" in str(err)
            or "Invalid" in type(err).__name__
            or "Validation" in type(err).__name__
        ):
            pytest.skip(f"rifiutato correttamente: {err}")
        raise
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state.name == "LOADED", entry.state


async def test_D_shared_echo_announces_once(hass: HomeAssistant, freezer: Any) -> None:
    """Due persone con lo stesso Echo: l'annuncio deve arrivare una volta sola."""
    freezer.move_to("2027-01-10 14:00:00+01:00")
    er.async_get(hass).async_get_or_create(
        "media_player", "alexa_media", "cucina", suggested_object_id="cucina"
    )
    hass.states.async_set("media_player.cucina", "idle", {})
    calls = async_mock_service(hass, "notify", "alexa_media")
    persons = [
        {
            "id": "mamma",
            "name": "Mamma",
            "color": "#111111",
            "role": "adult",
            "alexa_notify": "media_player.cucina",
        },
        {
            "id": "papa",
            "name": "Papà",
            "color": "#222222",
            "role": "adult",
            "alexa_notify": "media_player.cucina",
        },
    ]
    entry = await _setup(
        hass,
        persons,
        {"channels": ["speaker"], "quiet_start": None, "quiet_end": None, "offsets": [30]},
    )
    await hass.services.async_call(
        DOMAIN,
        "add_event",
        {
            "category": "famiglia",
            "summary": "Cena",
            "start": "2027-01-10 15:00",
            "persons": ["mamma", "papa"],
        },
        blocking=True,
    )
    uid = next(iter(_store(entry)))
    from homeassistant.util import dt as dt_util

    await entry.runtime_data.reminders.async_fire(
        uid, dt_util.parse_datetime("2027-01-10T14:30:00+01:00")
    )
    await hass.async_block_till_done()
    assert len(calls) == 1, f"annunci inviati: {len(calls)}"


async def test_E_move_after_done_reminds_again(hass: HomeAssistant) -> None:
    """Dopo 'Fatto', se l'evento viene spostato, i promemoria del nuovo orario dovrebbero tornare."""
    entry = await _setup(hass)
    await hass.services.async_call(
        DOMAIN,
        "add_event",
        {"category": "famiglia", "summary": "X", "start": "2027-01-10 15:00"},
        blocking=True,
    )
    uid = next(iter(_store(entry)))
    await hass.services.async_call(DOMAIN, "stop_reminder", {"uid": uid}, blocking=True)
    await hass.services.async_call(
        DOMAIN, "move_event", {"uid": uid, "start": "2027-01-17 15:00"}, blocking=True
    )
    assert not _store(entry)[uid].get("reminders_off")


async def test_F_entity_has_device_name(hass: HomeAssistant) -> None:
    """Regole 2026.11: entità con has_entity_name e dispositivo."""
    from homeassistant.helpers import entity_registry as er

    await _setup(hass)
    ent = er.async_get(hass).async_get(CAL)
    assert ent is not None and ent.device_id is not None


async def test_C2_bad_time_not_saved(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    with pytest.raises(Exception):
        await hass.services.async_call(
            DOMAIN,
            "add_event",
            {
                "category": "famiglia",
                "summary": "Gita",
                "start": "2027-01-10",
                "all_day_reminder": "19.00",
            },
            blocking=True,
        )
    saved = len(_store(entry))
    ok = await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert saved == 0 and ok, (
        f"eventi salvati nonostante l'errore: {saved}; integrazione ricaricata: {ok}, stato {entry.state}"
    )
