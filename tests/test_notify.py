"""Per-person notification settings: services that must exist, channels, Echo speakers and
their volume, the save command (admin only), the test message, and what a delivery sends."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.family_hub.const import (
    CONF_FAMILY_NAME,
    CONF_FIRST_WEEKDAY,
    CONF_LANGUAGE,
    DEFAULT_CATEGORIES,
    DOMAIN,
    OPT_CATEGORIES,
    OPT_PERSONS,
)
from custom_components.family_hub.notifier import (
    Delivery,
    Target,
    async_send,
    restore_delay,
    texts_for,
)
from custom_components.family_hub.notify_settings import alexa_targets, echo_entities
from custom_components.family_hub.reminders import _tablet_allowed

TEST_MESSAGE = texts_for("it")["test"]

PHONE = "mobile_app_pixel"
KITCHEN = "media_player.kueche"
LIVING = "media_player.wohnzimmer"


class Calls:
    """Records service calls in the order they happen, as (domain.service, data)."""

    def __init__(self) -> None:
        self.items: list[tuple[str, dict[str, Any]]] = []

    def named(self, name: str) -> list[dict[str, Any]]:
        return [data for call, data in self.items if call == name]


def _fire_restore(hass: HomeAssistant) -> Any:
    """Let the time it takes to speak the test message pass, so the old volumes come back."""
    return async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=restore_delay(TEST_MESSAGE) + 1)
    )


@pytest.fixture
def calls(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> Calls:
    recorder = Calls()
    # No waiting for real seconds in the tests: the volume is seen as reached at once.
    monkeypatch.setattr("custom_components.family_hub.notifier.ECHO_WAIT_MIN_SECONDS", 0)

    def record(name: str) -> Any:
        async def handler(call: ServiceCall) -> None:
            recorder.items.append((name, dict(call.data)))

        return handler

    async def set_volume(call: ServiceCall) -> None:
        # As an Echo does: its volume is the one set, and it reports it.
        recorder.items.append(("media_player.volume_set", dict(call.data)))
        hass.states.async_set(
            call.data["entity_id"], "idle", {"volume_level": call.data["volume_level"]}
        )

    hass.services.async_register("notify", PHONE, record(f"notify.{PHONE}"))
    hass.services.async_register("notify", "alexa_media", record("notify.alexa_media"))
    hass.services.async_register("media_player", "volume_set", set_volume)
    registry = er.async_get(hass)
    for name in ("kueche", "wohnzimmer"):
        registry.async_get_or_create("media_player", "alexa_media", name, suggested_object_id=name)
    hass.states.async_set(KITCHEN, "idle", {"volume_level": 0.3})
    hass.states.async_set(LIVING, "idle", {"volume_level": 0.5})
    return recorder


async def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={},
        options={
            CONF_FAMILY_NAME: "Esempio",
            CONF_LANGUAGE: "it",
            CONF_FIRST_WEEKDAY: "monday",
            OPT_PERSONS: [
                {"id": "mamma", "name": "Mamma", "color": "#2563EB", "role": "adult"},
                {"id": "sofia", "name": "Sofia", "color": "#FF8800", "role": "child"},
            ],
            OPT_CATEGORIES: [dict(c) for c in DEFAULT_CATEGORIES],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _save(client: Any, msg_id: int, persons: dict[str, Any]) -> dict[str, Any]:
    await client.send_json({"id": msg_id, "type": "family_hub/notify/save", "persons": persons})
    return await client.receive_json()


async def test_unknown_services_are_refused(
    hass: HomeAssistant, hass_ws_client: Any, calls: Calls
) -> None:
    entry = await _entry(hass)
    client = await hass_ws_client(hass)
    reply = await _save(client, 1, {"mamma": {"phone_notify": "mobile_app_nessuno"}})
    assert reply["success"] is False and reply["error"]["code"] == "unknown_service"
    reply = await _save(client, 2, {"mamma": {"alexa_notify": "media_player.garage"}})
    assert reply["error"]["code"] == "unknown_service"
    assert "phone_notify" not in entry.options[OPT_PERSONS][0]


async def test_existing_services_are_saved_with_channels_volume_and_quiet_hours(
    hass: HomeAssistant, hass_ws_client: Any, calls: Calls
) -> None:
    entry = await _entry(hass)
    client = await hass_ws_client(hass)
    reply = await _save(
        client,
        1,
        {
            "mamma": {
                "phone_notify": PHONE,
                "alexa_notify": KITCHEN,
                "alexa_volume": 60,
                "channels": ["alexa", "tablet"],
                "quiet_start": "23:00",
                "quiet_end": "06:30",
                "ha_user_id": "u-mamma",
            }
        },
    )
    assert reply["success"] is True, reply
    mamma = entry.options[OPT_PERSONS][0]
    assert mamma["phone_notify"] == PHONE
    assert mamma["alexa_notify"] == KITCHEN and mamma["alexa_volume"] == 60
    assert mamma["channels"] == ["alexa", "tablet"]
    assert (mamma["quiet_start"], mamma["quiet_end"]) == ("23:00", "06:30")
    assert mamma["ha_user_id"] == "u-mamma"
    assert entry.options[CONF_FAMILY_NAME] == "Esempio"  # the rest is untouched


@pytest.mark.parametrize(
    "changes",
    [
        {"alexa_volume": 101},
        {"alexa_volume": True},
        {"channels": ["email"]},
        {"quiet_start": "25:00"},
    ],
)
async def test_bad_values_are_refused(
    hass: HomeAssistant, hass_ws_client: Any, calls: Calls, changes: dict[str, Any]
) -> None:
    entry = await _entry(hass)
    client = await hass_ws_client(hass)
    reply = await _save(client, 1, {"sofia": changes})
    assert reply["success"] is False
    assert len(entry.options[OPT_PERSONS]) == 2


async def test_unknown_person_and_shared_user_are_refused(
    hass: HomeAssistant, hass_ws_client: Any, calls: Calls
) -> None:
    await _entry(hass)
    client = await hass_ws_client(hass)
    assert (await _save(client, 1, {"nessuno": {}}))["error"]["code"] == "not_found"
    await _save(client, 2, {"mamma": {"ha_user_id": "u-x"}})
    reply = await _save(client, 3, {"sofia": {"ha_user_id": "u-x"}})
    assert reply["success"] is False


async def test_non_admin_cannot_save_or_test(
    hass: HomeAssistant, hass_ws_client: Any, hass_read_only_access_token: str, calls: Calls
) -> None:
    entry = await _entry(hass)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    assert (await _save(client, 1, {"mamma": {"channels": []}}))["success"] is False
    assert entry.options[OPT_PERSONS][0].get("channels") is None
    await client.send_json(
        {"id": 2, "type": "family_hub/notify/test", "person": "mamma", "kind": "phone"}
    )
    assert (await client.receive_json())["success"] is False


async def test_a_service_already_kept_is_not_refused_when_other_fields_change(
    hass: HomeAssistant, hass_ws_client: Any, calls: Calls
) -> None:
    entry = await _entry(hass)
    client = await hass_ws_client(hass)
    await _save(client, 1, {"mamma": {"phone_notify": PHONE}})
    hass.services.async_remove("notify", PHONE)
    reply = await _save(client, 2, {"mamma": {"quiet_start": "22:30"}})
    assert reply["success"] is True, reply
    assert entry.options[OPT_PERSONS][0]["phone_notify"] == PHONE


async def test_phone_test_goes_only_to_the_chosen_service(
    hass: HomeAssistant, hass_ws_client: Any, calls: Calls
) -> None:
    await _entry(hass)
    client = await hass_ws_client(hass)
    await _save(client, 1, {"mamma": {"phone_notify": PHONE}})
    await client.send_json(
        {"id": 2, "type": "family_hub/notify/test", "person": "mamma", "kind": "phone"}
    )
    reply = await client.receive_json()
    assert reply["result"] == {"sent": 1}
    assert [c for c, _ in calls.items] == [f"notify.{PHONE}"]


async def test_test_without_a_chosen_service_is_refused(
    hass: HomeAssistant, hass_ws_client: Any, calls: Calls
) -> None:
    await _entry(hass)
    client = await hass_ws_client(hass)
    await client.send_json(
        {"id": 1, "type": "family_hub/notify/test", "person": "mamma", "kind": "alexa"}
    )
    assert (await client.receive_json())["error"]["code"] == "no_service"
    await client.send_json(
        {"id": 2, "type": "family_hub/notify/test", "person": "mamma", "kind": "phone"}
    )
    assert (await client.receive_json())["error"]["code"] == "no_service"
    assert calls.items == []


async def test_echo_test_sets_volume_announces_then_restores(
    hass: HomeAssistant, hass_ws_client: Any, calls: Calls
) -> None:
    await _entry(hass)
    client = await hass_ws_client(hass)
    await _save(client, 1, {"mamma": {"alexa_notify": "all", "alexa_volume": 60}})
    await client.send_json(
        {"id": 2, "type": "family_hub/notify/test", "person": "mamma", "kind": "alexa"}
    )
    assert (await client.receive_json())["result"] == {"sent": 2}
    # Volume first, then the announcement, then the old volume is put back.
    assert [c for c, _ in calls.items] == [
        "media_player.volume_set",
        "media_player.volume_set",
        "notify.alexa_media",
    ]
    assert [d["volume_level"] for d in calls.named("media_player.volume_set")] == [0.6, 0.6]
    (announce,) = calls.named("notify.alexa_media")
    assert announce["target"] == [KITCHEN, LIVING]
    assert announce["data"] == {"type": "announce"}
    _fire_restore(hass)
    await hass.async_block_till_done()
    restored = calls.named("media_player.volume_set")[2:]
    assert sorted((r["entity_id"], r["volume_level"]) for r in restored) == [
        (KITCHEN, 0.3),
        (LIVING, 0.5),
    ]


async def test_echo_without_volume_sets_nothing(
    hass: HomeAssistant, hass_ws_client: Any, calls: Calls
) -> None:
    await _entry(hass)
    client = await hass_ws_client(hass)
    await _save(client, 1, {"mamma": {"alexa_notify": KITCHEN}})
    await client.send_json(
        {"id": 2, "type": "family_hub/notify/test", "person": "mamma", "kind": "alexa"}
    )
    assert (await client.receive_json())["result"] == {"sent": 1}
    assert [c for c, _ in calls.items] == ["notify.alexa_media"]
    _fire_restore(hass)
    await hass.async_block_till_done()
    assert [c for c, _ in calls.items] == ["notify.alexa_media"]


async def test_unknown_volume_goes_back_to_the_fallback_not_left_high(
    hass: HomeAssistant, hass_ws_client: Any, calls: Calls
) -> None:
    # The Echo reports no volume before the change: it must not be left at the chosen one.
    hass.states.async_set(KITCHEN, "idle", {})
    await _entry(hass)
    client = await hass_ws_client(hass)
    await _save(client, 1, {"mamma": {"alexa_notify": KITCHEN, "alexa_volume": 40}})
    await client.send_json(
        {"id": 2, "type": "family_hub/notify/test", "person": "mamma", "kind": "alexa"}
    )
    await client.receive_json()
    _fire_restore(hass)
    await hass.async_block_till_done()
    restored = [d for d in calls.named("media_player.volume_set") if d["volume_level"] == 0.3]
    assert [d["entity_id"] for d in restored] == [KITCHEN]


async def test_test_uses_the_values_on_the_screen_not_the_saved_ones(
    hass: HomeAssistant, hass_ws_client: Any, calls: Calls
) -> None:
    await _entry(hass)
    client = await hass_ws_client(hass)
    await _save(client, 1, {"mamma": {"alexa_notify": KITCHEN, "alexa_volume": 60}})
    await client.send_json(
        {
            "id": 2,
            "type": "family_hub/notify/test",
            "person": "mamma",
            "kind": "alexa",
            "alexa_notify": LIVING,
            "alexa_volume": 25,
        }
    )
    assert (await client.receive_json())["result"] == {"sent": 1}
    (volume,) = calls.named("media_player.volume_set")
    assert (volume["entity_id"], volume["volume_level"]) == (LIVING, 0.25)
    assert calls.named("notify.alexa_media")[0]["target"] == [LIVING]
    _fire_restore(hass)
    await hass.async_block_till_done()


async def test_test_refuses_a_bad_volume_or_an_unknown_echo(
    hass: HomeAssistant, hass_ws_client: Any, calls: Calls
) -> None:
    await _entry(hass)
    client = await hass_ws_client(hass)
    base = {"type": "family_hub/notify/test", "person": "mamma", "kind": "alexa"}
    cases = [
        ({"alexa_notify": KITCHEN, "alexa_volume": 101}, "bad_request"),
        ({"alexa_notify": KITCHEN, "alexa_volume": True}, "bad_request"),
        ({"alexa_notify": "media_player.garage", "alexa_volume": 30}, "unknown_service"),
    ]
    for msg_id, (extra, code) in enumerate(cases, start=1):
        await client.send_json({"id": msg_id, **base, **extra})
        assert (await client.receive_json())["error"]["code"] == code
    assert calls.items == []


async def test_all_leaves_out_unavailable_groups_fire_tv_and_this_device(
    hass: HomeAssistant, calls: Calls
) -> None:
    registry = er.async_get(hass)
    for name in ("ovunque", "fire_tv_demo", "this_device", "vecchio", "spento"):
        registry.async_get_or_create("media_player", "alexa_media", name, suggested_object_id=name)
    hass.states.async_set("media_player.ovunque", "idle", {"friendly_name": "Ovunque"})
    hass.states.async_set("media_player.fire_tv_demo", "idle", {})
    hass.states.async_set("media_player.this_device", "idle", {})
    hass.states.async_set("media_player.vecchio", "unavailable", {})
    registry.async_update_entity("media_player.spento", disabled_by=er.RegistryEntryDisabler.USER)
    assert echo_entities(hass) == [KITCHEN, LIVING]
    assert alexa_targets(hass, "all") == [KITCHEN, LIVING]


async def test_an_echo_that_fails_does_not_stop_the_others(
    hass: HomeAssistant, calls: Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("custom_components.family_hub.notifier.ECHO_WAIT_MIN_SECONDS", 0)
    recorded: list[str] = []

    async def volume(call: ServiceCall) -> None:
        recorded.append(call.data["entity_id"])
        if call.data["entity_id"] == KITCHEN:
            raise RuntimeError("Echo offline")
        hass.states.async_set(LIVING, "idle", {"volume_level": call.data["volume_level"]})

    hass.services.async_register("media_player", "volume_set", volume)
    from custom_components.family_hub.notifier import announce_on_echos

    await announce_on_echos(hass, [KITCHEN, LIVING], TEST_MESSAGE, 40)
    assert recorded == [KITCHEN, LIVING]
    assert [c for c, _ in calls.items] == ["notify.alexa_media"]
    _fire_restore(hass)
    await hass.async_block_till_done()


def _target(**overrides: Any) -> Target:
    base: dict[str, Any] = {
        "name": "Mamma",
        "phone_notify": PHONE,
        "speaker": None,
        "alexa_notify": None,
        "quiet": False,
        "channels": frozenset({"phone", "alexa", "tablet"}),
        "alexa_volume": None,
    }
    base.update(overrides)
    return Target(**base)


def _delivery(targets: list[Target], channels: set[str]) -> Delivery:
    return Delivery(
        title="Promemoria",
        message="09:00 · Dentista",
        notification_id="family_hub_test",
        targets=targets,
        channels=frozenset(channels),
        tts_entity=None,
        tablet=True,
        uid="u1",
    )


async def test_phone_is_sent_only_to_the_chosen_service(hass: HomeAssistant, calls: Calls) -> None:
    await async_send(hass, _delivery([_target()], {"phone"}))
    assert [c for c, _ in calls.items] == [f"notify.{PHONE}"]


async def test_a_person_who_refuses_a_channel_gets_nothing_there(
    hass: HomeAssistant, calls: Calls
) -> None:
    no_phone = _target(channels=frozenset({"alexa"}), alexa_notify=KITCHEN)
    await async_send(hass, _delivery([no_phone], {"phone", "speaker"}))
    assert [c for c, _ in calls.items] == ["notify.alexa_media"]


async def test_tablet_popup_needs_someone_who_accepts_it() -> None:
    assert _tablet_allowed([_target()]) is True
    assert _tablet_allowed([_target(channels=frozenset({"phone"}))]) is False
    assert _tablet_allowed([]) is True
