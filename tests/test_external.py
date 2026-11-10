"""External calendars (ICS): parsing, the read-only entity, limits, failed downloads that keep
the last copy, rubbish and holiday reminders, and who may change them."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.family_hub import external, external_api
from custom_components.family_hub.const import (
    CONF_FAMILY_NAME,
    CONF_FIRST_WEEKDAY,
    CONF_LANGUAGE,
    DEFAULT_CATEGORIES,
    DOMAIN,
    OPT_CATEGORIES,
    OPT_PERSONS,
    OPT_REMINDERS,
)
from custom_components.family_hub.external import OPT_EXTERNAL, ExternalError, parse

WASTE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:rest-1
DTSTART;VALUE=DATE:20261109
DTEND;VALUE=DATE:20261110
SUMMARY:Indifferenziato
RRULE:FREQ=WEEKLY;BYDAY=MO
END:VEVENT
END:VCALENDAR
"""

HOLIDAY_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:ferien-1
DTSTART;VALUE=DATE:20261101
DTEND;VALUE=DATE:20261114
SUMMARY:Herbstferien
END:VEVENT
END:VCALENDAR
"""

PERSON = {"id": "mamma", "name": "Mamma", "color": "#2563EB", "role": "adult"}


def _source(**overrides: Any) -> dict[str, Any]:
    source: dict[str, Any] = {
        "id": "rest",
        "name": "Rifiuti",
        "type": "rifiuti",
        "color": "#64748B",
        "icon": "trash",
        "persons": ["mamma"],
        "remind_at": "19:00",
        "morning_at": "07:00",
        "return_notice": False,
    }
    source.update(overrides)
    return source


async def _setup(
    hass: HomeAssistant,
    sources: list[dict[str, Any]],
    text: dict[str, str],
    extra: dict[str, Any] | None = None,
) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={},
        options={
            CONF_FAMILY_NAME: "Esempio",
            CONF_LANGUAGE: "it",
            CONF_FIRST_WEEKDAY: "monday",
            OPT_PERSONS: [PERSON],
            OPT_CATEGORIES: [dict(c) for c in DEFAULT_CATEGORIES],
            OPT_EXTERNAL: sources,
            OPT_REMINDERS: {"channels": ["tablet"], "quiet_start": None, "quiet_end": None},
            **(extra or {}),
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    manager = entry.runtime_data.external
    for source_id, content in text.items():
        await manager.async_set_content(source_id, content)
    return entry


def test_recurring_and_all_day_events_are_expanded() -> None:
    calendar = parse(WASTE_ICS)
    timeline = calendar.timeline_tz(external.dt_util.get_default_time_zone())
    from datetime import timedelta

    start = datetime(2026, 11, 1, tzinfo=external.dt_util.get_default_time_zone())
    events = list(timeline.overlapping(start, start + timedelta(days=30)))
    assert [e.summary for e in events] == ["Indifferenziato"] * 4
    assert all(not isinstance(e.start, datetime) for e in events)  # all-day: dates


def test_invalid_and_too_big_files_are_refused() -> None:
    with pytest.raises(ExternalError) as bad:
        parse("not a calendar")
    assert bad.value.code == "invalid_ics"
    with pytest.raises(ExternalError) as big:
        parse("BEGIN:VCALENDAR\n" + "X-PAD:" + "a" * (6 * 1024 * 1024) + "\nEND:VCALENDAR\n")
    assert big.value.code == "too_large"


def test_only_http_https_and_webcal_are_allowed() -> None:
    assert external.check_url("webcal://example.org/a.ics") == "https://example.org/a.ics"
    assert external.check_url("https://example.org/a.ics?x=1") == "https://example.org/a.ics?x=1"
    for bad in ("ftp://example.org/a.ics", "file:///etc/passwd", "example.org"):
        with pytest.raises(ExternalError) as err:
            external.check_url(bad)
        assert err.value.code == "bad_url"


async def test_the_calendar_entity_is_read_only_and_shows_the_events(hass: HomeAssistant) -> None:
    from datetime import timedelta

    entry = await _setup(hass, [_source(id="rest", type="rifiuti")], {"rest": WASTE_ICS})
    assert hass.states.get("calendar.family_hub_ext_rest") is not None
    entity = entry.runtime_data.external.entities["rest"]
    start = datetime(2026, 11, 1, tzinfo=external.dt_util.get_default_time_zone())
    events = await entity.async_get_events(hass, start, start + timedelta(days=30))
    assert len(events) == 4
    assert entity.supported_features in (None, 0)  # no create, update or delete


async def test_a_failed_download_keeps_the_last_valid_copy(
    hass: HomeAssistant, monkeypatch: Any
) -> None:
    entry = await _setup(
        hass,
        [_source(id="rest", url="https://example.org/rest.ics")],
        {"rest": WASTE_ICS},
    )
    manager = entry.runtime_data.external

    async def fails(_hass: HomeAssistant, _url: str) -> str:
        raise ExternalError("download_failed")

    monkeypatch.setattr(external, "download", fails)
    await manager.async_refresh("rest")
    assert manager.content("rest") == WASTE_ICS  # the last valid copy stays
    assert manager.status("rest")["error"] == "download_failed"


async def test_a_good_download_replaces_the_copy_and_clears_the_error(
    hass: HomeAssistant, monkeypatch: Any
) -> None:
    entry = await _setup(
        hass, [_source(id="rest", url="https://example.org/rest.ics")], {"rest": WASTE_ICS}
    )
    manager = entry.runtime_data.external

    async def ok(_hass: HomeAssistant, _url: str) -> str:
        return HOLIDAY_ICS

    monkeypatch.setattr(external, "download", ok)
    await manager.async_refresh("rest")
    assert manager.content("rest") == HOLIDAY_ICS
    assert manager.status("rest")["error"] is None
    assert manager.status("rest")["updated"]


async def test_rubbish_is_announced_the_evening_before_and_the_morning_of(
    hass: HomeAssistant, freezer: Any
) -> None:
    # The reminders are planned from the time of the setup: start before the evening.
    freezer.move_to("2026-11-08 12:00:00+01:00")
    calls = async_mock_service(hass, "persistent_notification", "create")
    await _setup(hass, [_source()], {"rest": WASTE_ICS})
    # Monday 9 November is the pickup: Sunday evening announces it, Monday morning says today.
    freezer.move_to("2026-11-08 19:00:00+01:00")
    async_fire_time_changed(hass, datetime.fromisoformat("2026-11-08 19:00:00+01:00"))
    await hass.async_block_till_done()
    freezer.move_to("2026-11-09 07:00:00+01:00")
    async_fire_time_changed(hass, datetime.fromisoformat("2026-11-09 07:00:00+01:00"))
    await hass.async_block_till_done()
    messages = [c.data["message"] for c in calls]
    assert "Domani: Indifferenziato" in messages
    assert "Oggi: Indifferenziato" in messages


async def test_holidays_are_only_announced_when_asked_for_the_return(
    hass: HomeAssistant, freezer: Any
) -> None:
    # The reminders are planned from the time of the setup: start before the evening.
    freezer.move_to("2026-11-08 12:00:00+01:00")
    calls = async_mock_service(hass, "persistent_notification", "create")
    await _setup(
        hass,
        [
            _source(id="ferien", type="vacanze_scuola", return_notice=False),
            _source(id="ferien2", type="vacanze_scuola", return_notice=True, persons=["mamma"]),
        ],
        {"ferien": HOLIDAY_ICS, "ferien2": HOLIDAY_ICS},
    )
    freezer.move_to("2026-11-13 19:00:00+01:00")
    async_fire_time_changed(hass, datetime.fromisoformat("2026-11-13 19:00:00+01:00"))
    await hass.async_block_till_done()
    messages = [c.data["message"] for c in calls]
    # Only the calendar that asked for it: the return is on the 14th.
    assert messages.count("Domani si rientra") == 1


async def test_only_an_administrator_can_change_external_calendars(
    hass: HomeAssistant, hass_ws_client: Any, hass_read_only_access_token: str, monkeypatch: Any
) -> None:
    await _setup(hass, [], {})

    async def ok(_hass: HomeAssistant, _url: str) -> str:
        return WASTE_ICS

    monkeypatch.setattr(external_api, "download", ok)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json(
        {
            "id": 1,
            "type": "family_hub/ics/add",
            "calendar": {"name": "Rifiuti", "type": "rifiuti", "persons": ["mamma"]},
            "url": "https://example.org/rest.ics",
        }
    )
    assert (await client.receive_json())["success"] is False


async def test_adding_a_file_stores_it_and_a_bad_file_is_refused(
    hass: HomeAssistant, hass_ws_client: Any
) -> None:
    entry = await _setup(hass, [], {})
    client = await hass_ws_client(hass)
    bad = {
        "id": 1,
        "type": "family_hub/ics/add",
        "calendar": {"name": "Ferien", "type": "vacanze_scuola", "persons": ["mamma"]},
        "content": "garbage",
    }
    await client.send_json(bad)
    reply = await client.receive_json()
    assert reply["success"] is False and reply["error"]["code"] == "invalid_ics"
    assert entry.options.get(OPT_EXTERNAL, []) == []

    good = {**bad, "id": 2, "content": HOLIDAY_ICS}
    await client.send_json(good)
    reply = await client.receive_json()
    assert reply["success"] is True, reply
    await hass.async_block_till_done()
    assert len(entry.options[OPT_EXTERNAL]) == 1
    assert hass.states.get(f"calendar.family_hub_ext_{reply['result']['id']}") is not None


TWO_BINS_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:r1
DTSTART;VALUE=DATE:20261109
DTEND;VALUE=DATE:20261110
SUMMARY:Indifferenziato
END:VEVENT
BEGIN:VEVENT
UID:r2
DTSTART;VALUE=DATE:20261109
DTEND;VALUE=DATE:20261110
SUMMARY:Organico
END:VEVENT
END:VCALENDAR
"""


def test_waste_kinds_are_recognised_from_the_title() -> None:
    from custom_components.family_hub.external import waste_kind

    cases = {
        "Restmüll": "restmuell",
        "RESTABFALL": "restmuell",
        "Biotonne": "bio",
        "Bioabfall": "bio",
        "Altpapier": "papier",
        "Papiertonne": "papier",
        "Gelbe Tonne": "gelb",
        "Gelber Sack": "gelb",
        "Wertstoff": "gelb",
        "Abfuhr: Restabfall": "restmuell",
        "Abfuhr: Bioabfall": "bio",
        "Abfuhr: Papierabfall": "papier",
        "Abfuhr: Gelbe Tonne": "gelb",
        # Anything else is "Altro", the type without a text to look for.
        "Glas": "glas",
        "Abfuhr": "altro",
    }
    for title, kind in cases.items():
        assert waste_kind(title, "de") == kind, title


async def test_two_pickups_on_one_day_make_one_reminder(hass: HomeAssistant, freezer: Any) -> None:
    # The reminders are planned from the time of the setup: start before the evening.
    freezer.move_to("2026-11-08 12:00:00+01:00")
    calls = async_mock_service(hass, "persistent_notification", "create")
    await _setup(hass, [_source()], {"rest": TWO_BINS_ICS})
    freezer.move_to("2026-11-08 19:00:00+01:00")
    async_fire_time_changed(hass, datetime.fromisoformat("2026-11-08 19:00:00+01:00"))
    await hass.async_block_till_done()
    messages = [c.data["message"] for c in calls]
    assert [m for m in messages if "Indiff" in m] == ["Domani: Indifferenziato, Organico"]


async def test_fatto_on_the_evening_also_ends_the_morning_reminder(
    hass: HomeAssistant, freezer: Any
) -> None:
    # The reminders are planned from the time of the setup: start before the evening.
    freezer.move_to("2026-11-08 12:00:00+01:00")
    calls = async_mock_service(hass, "persistent_notification", "create")
    entry = await _setup(hass, [_source()], {"rest": WASTE_ICS})
    manager = entry.runtime_data.external
    uid = "ext-rest-2026-11-09"
    await manager.async_action("done", uid)
    freezer.move_to("2026-11-09 07:00:00+01:00")
    async_fire_time_changed(hass, datetime.fromisoformat("2026-11-09 07:00:00+01:00"))
    await hass.async_block_till_done()
    # The morning summary may list the rubbish of the day; the reminder itself must not come.
    reminders = [
        c.data["message"]
        for c in calls
        if "Indiff" in c.data["message"] and "summary" not in c.data.get("notification_id", "")
    ]
    assert reminders == []


async def test_snooze_one_hour_sends_it_again(hass: HomeAssistant, freezer: Any) -> None:
    # The reminders are planned from the time of the setup: start before the evening.
    freezer.move_to("2026-11-08 12:00:00+01:00")
    calls = async_mock_service(hass, "persistent_notification", "create")
    entry = await _setup(hass, [_source()], {"rest": WASTE_ICS})
    manager = entry.runtime_data.external
    freezer.move_to("2026-11-08 19:00:00+01:00")
    async_fire_time_changed(hass, datetime.fromisoformat("2026-11-08 19:00:00+01:00"))
    await hass.async_block_till_done()

    # The evening summary (20:00) also lists the rubbish: only the reminders are counted here.
    def reminders() -> list[Any]:
        return [
            c
            for c in calls
            if "Indiff" in c.data["message"] and "summary" not in c.data["notification_id"]
        ]

    assert len(reminders()) == 1
    await manager.async_action("snooze", "ext-rest-2026-11-09", 60)
    freezer.move_to("2026-11-08 20:00:00+01:00")
    async_fire_time_changed(hass, datetime.fromisoformat("2026-11-08 20:00:00+01:00"))
    await hass.async_block_till_done()
    assert len(reminders()) == 2


async def test_the_entity_keeps_its_id_and_takes_the_chosen_name(hass: HomeAssistant) -> None:
    await _setup(hass, [_source(name="Abfuhrtermine")], {"rest": WASTE_ICS})
    state = hass.states.get("calendar.family_hub_ext_rest")
    assert state is not None
    assert state.attributes["friendly_name"] == "Abfuhrtermine"


async def test_waste_colours_can_be_changed_by_an_admin_only(
    hass: HomeAssistant, hass_ws_client: Any, hass_read_only_access_token: str
) -> None:
    entry = await _setup(hass, [], {})
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "family_hub/ics/styles", "styles": {"bio": "#112233"}})
    assert (await client.receive_json())["success"] is True
    assert entry.options["waste_styles"] == {"bio": "#112233"}
    await client.send_json(
        {"id": 2, "type": "family_hub/ics/styles", "styles": {"sport": "#112233"}}
    )
    assert (await client.receive_json())["error"]["code"] == "bad_type"
    readonly = await hass_ws_client(hass, hass_read_only_access_token)
    await readonly.send_json(
        {"id": 3, "type": "family_hub/ics/styles", "styles": {"bio": "#000000"}}
    )
    assert (await readonly.receive_json())["success"] is False


async def test_a_home_assistant_rubbish_calendar_is_announced_like_an_ics_file(
    hass: HomeAssistant, freezer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A calendar from Home Assistant, chosen as rubbish in Fonti, gets the evening and morning
    reminders too. Its events for the day come from _ha_names_on, which asks calendar.get_events;
    here that read is replaced, because the test has no calendar integration to answer it."""
    # The reminders are planned from the time of the setup: start before the evening.
    freezer.move_to("2026-11-08 12:00:00+01:00")
    calls = async_mock_service(hass, "persistent_notification", "create")
    asked: list[tuple[str, str]] = []

    async def names_on(self: Any, entity_id: str, day: Any) -> list[str]:
        asked.append((entity_id, day.isoformat()))
        return ["Indifferenziato"] if day.isoformat() == "2026-11-09" else []

    monkeypatch.setattr(external.ExternalManager, "_ha_names_on", names_on)
    await _setup(
        hass,
        [],
        {},
        {
            "sources": {
                "calendar_styles": {
                    "calendar.rifiuti_bianco": {"name": "", "type": "rifiuti", "color": "#64748B"},
                    "calendar.festa": {"name": "", "type": "altro", "color": "#64748B"},
                }
            }
        },
    )
    freezer.move_to("2026-11-08 19:00:00+01:00")
    async_fire_time_changed(hass, datetime.fromisoformat("2026-11-08 19:00:00+01:00"))
    await hass.async_block_till_done()
    freezer.move_to("2026-11-09 07:00:00+01:00")
    async_fire_time_changed(hass, datetime.fromisoformat("2026-11-09 07:00:00+01:00"))
    await hass.async_block_till_done()
    messages = [c.data["message"] for c in calls]
    assert "Domani: Indifferenziato" in messages
    assert "Oggi: Indifferenziato" in messages
    # The rubbish calendar is read for the reminders; the chosen calendars too, for the summary.
    assert {entity for entity, _ in asked} == {"calendar.rifiuti_bianco", "calendar.festa"}
    assert ("calendar.rifiuti_bianco", "2026-11-09") in asked


def test_rubbish_types_are_checked_and_colour_names_accepted() -> None:
    from custom_components.family_hub.waste import WasteTypeError, clean_types, type_of

    types = clean_types(
        [
            {"label": "Organico", "icon": "mdi:flower", "pattern": "Bio", "color": "light-green"},
            {"label": "Altro", "icon": "mdi:dump-truck", "pattern": "", "color": "#9c27b0"},
        ]
    )
    assert types[0] == {
        "id": "organico",
        "label": "Organico",
        "icon": "mdi:flower",
        "pattern": "Bio",
        "color": "#8BC34A",
    }
    assert type_of("Abfuhr: Bioabfall", types)["label"] == "Organico"
    assert type_of("Sperrmüll", types)["label"] == "Altro"
    for bad in (
        [],
        [{"label": "", "icon": "mdi:flower", "color": "#000000"}],
        [{"label": "X", "icon": "flower", "color": "#000000"}],
        [{"label": "X", "icon": "mdi:flower", "color": "verde"}],
    ):
        with pytest.raises(WasteTypeError):
            clean_types(bad)


async def test_rubbish_types_are_saved_by_an_admin_and_listed(
    hass: HomeAssistant, hass_ws_client: Any, hass_read_only_access_token: str
) -> None:
    entry = await _setup(hass, [], {})
    client = await hass_ws_client(hass)
    types = [
        {"label": "Umido", "icon": "mdi:leaf", "pattern": "Bio, Umido", "color": "#00AA00"},
        {"label": "Altro", "icon": "mdi:dump-truck", "pattern": "", "color": "#9C27B0"},
    ]
    await client.send_json({"id": 1, "type": "family_hub/ics/waste_types", "types": types})
    reply = await client.receive_json()
    assert reply["success"] is True, reply
    assert [t["label"] for t in entry.options["waste_types"]] == ["Umido", "Altro"]
    await client.send_json({"id": 2, "type": "family_hub/ics/list"})
    listed = (await client.receive_json())["result"]
    assert listed["waste_types"][0]["icon"] == "mdi:leaf"
    assert listed["waste_styles"]["umido"] == "#00AA00"
    await client.send_json(
        {"id": 3, "type": "family_hub/ics/waste_types", "types": [{"label": ""}]}
    )
    bad = await client.receive_json()
    assert bad["success"] is False and "label" in bad["error"]["message"]
    readonly = await hass_ws_client(hass, hass_read_only_access_token)
    await readonly.send_json({"id": 4, "type": "family_hub/ics/waste_types", "types": types})
    assert (await readonly.receive_json())["success"] is False
