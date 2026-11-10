"""The morning and evening summaries (07:00 and 20:00): nothing is sent when there is nothing to
say; each person gets their own appointments and the family's; the linked calendars are part of
it ("Rifiuti: Organico", one holiday line); Alexa only when chosen for the summary; a switch."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.family_hub import external
from custom_components.family_hub.const import (
    CONF_FAMILY_NAME,
    CONF_FIRST_WEEKDAY,
    CONF_LANGUAGE,
    DOMAIN,
    OPT_CATEGORIES,
    OPT_PERSONS,
    OPT_REMINDERS,
)

MAMMA = {
    "id": "mamma",
    "name": "Mamma",
    "color": "#2563EB",
    "role": "adult",
    "phone_notify": "mobile_app_mamma",
    "alexa_notify": "media_player.cucina",
}
SOFIA = {"id": "sofia", "name": "Sofia", "color": "#FF8800", "role": "child"}
KITCHEN = "media_player.cucina"


def local(hour: int, minute: int = 0) -> datetime:
    """2026-11-10 at the given time in the instance time zone."""
    return datetime(2026, 11, 10, hour, minute, tzinfo=dt_util.get_default_time_zone())


async def _setup(
    hass: HomeAssistant,
    reminders: dict[str, Any] | None = None,
    sources: dict[str, Any] | None = None,
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_FAMILY_NAME: "Esempio", CONF_LANGUAGE: "it", CONF_FIRST_WEEKDAY: "monday"},
        options={
            OPT_PERSONS: [dict(MAMMA), dict(SOFIA)],
            OPT_CATEGORIES: [{"id": "famiglia", "name": "Famiglia", "color": "#3B82F6"}],
            OPT_REMINDERS: reminders or {},
            "sources": sources or {},
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "media_player", "alexa_media", "cucina", suggested_object_id="cucina"
    )
    hass.states.async_set(KITCHEN, "idle", {})
    return entry


async def _add(hass: HomeAssistant, summary: str, start: str, persons: list[str]) -> None:
    await hass.services.async_call(
        DOMAIN,
        "add_event",
        {"category": "famiglia", "summary": summary, "start": start, "persons": persons},
        blocking=True,
    )


async def test_nothing_to_say_sends_nothing(hass: HomeAssistant, freezer: Any) -> None:
    freezer.move_to(local(8))
    entry = await _setup(hass)
    phone = async_mock_service(hass, "notify", "mobile_app_mamma")
    tablet = async_mock_service(hass, "persistent_notification", "create")
    await entry.runtime_data.reminders.async_send_summary("morning")
    assert phone == [] and tablet == []


async def test_each_person_gets_their_own_and_the_familys(
    hass: HomeAssistant, freezer: Any
) -> None:
    freezer.move_to(local(8))
    entry = await _setup(hass, {"summary_channels": ["phone", "tablet"]})
    await _add(hass, "Solo Mamma", "2026-11-10 09:00:00", ["mamma"])
    await _add(hass, "Solo Sofia", "2026-11-10 10:00:00", ["sofia"])
    await _add(hass, "Di tutti", "2026-11-10 19:00:00", [])
    phone = async_mock_service(hass, "notify", "mobile_app_mamma")
    tablet = async_mock_service(hass, "persistent_notification", "create")
    await entry.runtime_data.reminders.async_send_summary("morning")
    (mamma,) = phone
    assert "Solo Mamma" in mamma.data["message"] and "Di tutti" in mamma.data["message"]
    assert "Solo Sofia" not in mamma.data["message"]
    # The tablet shows the whole family's day, once.
    (family,) = tablet
    assert "Solo Sofia" in family.data["message"] and "Solo Mamma" in family.data["message"]


async def test_rubbish_and_holidays_of_the_linked_calendars_are_in_the_summary(
    hass: HomeAssistant, freezer: Any, monkeypatch: Any
) -> None:
    freezer.move_to(local(8))
    days = {
        "calendar.rifiuti_bio": ["Umido"],
        "calendar.ferien": ["Herbstferien", "Ferien Nebenzeile"],
    }

    async def names_on(self: Any, entity_id: str, day: Any) -> list[str]:
        return days.get(entity_id, []) if day.isoformat() == "2026-11-10" else []

    monkeypatch.setattr(external.ExternalManager, "_ha_names_on", names_on)
    entry = await _setup(
        hass,
        {"summary_channels": ["tablet"]},
        {
            "calendar_styles": {
                "calendar.rifiuti_bio": {"type": "rifiuti", "color": "#8B5A2B", "persons": []},
                "calendar.ferien": {"type": "vacanze_scuola", "color": "#0EA5E9", "persons": []},
            }
        },
    )
    tablet = async_mock_service(hass, "persistent_notification", "create")
    await entry.runtime_data.reminders.async_send_summary("morning")
    (family,) = tablet
    message = family.data["message"]
    assert "Rifiuti: Organico" in message
    # Two holiday titles on the same day: one line.
    assert message.count("Vacanze scuola") == 1


async def test_alexa_is_off_by_default_and_on_when_chosen(
    hass: HomeAssistant, freezer: Any
) -> None:
    freezer.move_to(local(8))
    entry = await _setup(hass)
    await _add(hass, "Solo Mamma", "2026-11-10 09:00:00", ["mamma"])
    phone = async_mock_service(hass, "notify", "mobile_app_mamma")
    alexa = async_mock_service(hass, "notify", "alexa_media")
    await entry.runtime_data.reminders.async_send_summary("morning")
    assert len(phone) == 1 and alexa == []

    hass.config_entries.async_update_entry(
        entry,
        options={**entry.options, OPT_REMINDERS: {"summary_channels": ["phone", "alexa"]}},
    )
    await entry.runtime_data.reminders.async_send_summary("morning")
    assert len(alexa) == 1
    assert alexa[0].data["target"] == [KITCHEN]


async def test_the_summary_save_command_keeps_the_time_when_switched_off(
    hass: HomeAssistant, hass_ws_client: Any
) -> None:
    entry = await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json(
        {
            "id": 1,
            "type": "family_hub/summary/save",
            "reminders": {
                "morning_summary": "06:45",
                "morning_summary_on": False,
                "summary_channels": ["alexa", "tablet"],
            },
        }
    )
    assert (await client.receive_json())["success"] is True
    saved = entry.options[OPT_REMINDERS]
    assert saved["morning_summary_on"] is False
    assert saved["morning_summary"] == "06:45"
    assert saved["summary_channels"] == ["alexa", "tablet"]
    await client.send_json(
        {"id": 2, "type": "family_hub/summary/save", "reminders": {"summary_channels": ["email"]}}
    )
    assert (await client.receive_json())["success"] is False


async def test_the_switch_off_sends_nothing(hass: HomeAssistant, freezer: Any) -> None:
    freezer.move_to(local(8))
    entry = await _setup(hass, {"morning_summary_on": False})
    await _add(hass, "Solo Mamma", "2026-11-10 09:00:00", ["mamma"])
    phone = async_mock_service(hass, "notify", "mobile_app_mamma")
    tablet = async_mock_service(hass, "persistent_notification", "create")
    await entry.runtime_data.reminders.async_send_summary("morning")
    assert phone == [] and tablet == []
