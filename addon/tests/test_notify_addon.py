"""Notification settings ("Avvisi") in the add-on: who reads and changes what, that the page
offers only services Home Assistant has, and that a test message is asked for only for the
services a person chose (the integration sends it)."""

from __future__ import annotations

import asyncio
from typing import Any

from tests.fake_ha import FakeHA
from tests.helpers import ADULT_USER, CHILD_USER, GUEST_USER, connect, request, shutdown, started


def _run(scenario: Any) -> None:
    asyncio.run(scenario())


def test_adult_reads_everyone_child_only_self_guest_nothing() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            adult = await connect(client, ADULT_USER)
            result = (await request(adult, {"id": 1, "op": "notify_get"}))["result"]
            assert {p["id"] for p in result["persons"]} == {"sofia", "mamma", "ospite"}
            assert [s["name"] for s in result["services"]["phone"]] == [
                "mobile_app_mamma",
                "mobile_app_sofia",
            ]
            assert [s["label"] for s in result["services"]["phone"]] == ["Mamma", "Sofia"]
            assert [s["entity_id"] for s in result["services"]["alexa"]] == [
                "media_player.kueche",
                "media_player.wohnzimmer",
            ]
            assert any(u["name"] == "Mamma" for u in result["users"])
            await adult.close()
            child = await connect(client, CHILD_USER)
            own = await request(child, {"id": 2, "op": "notify_get"})
            assert [p["id"] for p in own["result"]["persons"]] == ["sofia"]
            assert "users" not in own["result"]
            await child.close()
            guest = await connect(client, GUEST_USER)
            assert (await request(guest, {"id": 3, "op": "notify_get"}))["error"] == "forbidden"
            await guest.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_child_saves_own_settings_but_not_others_or_the_user_link() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            child = await connect(client, CHILD_USER)
            mine = await request(
                child,
                {
                    "id": 1,
                    "op": "notify_save",
                    "persons": {
                        "sofia": {"phone_notify": "mobile_app_sofia", "channels": ["phone"]}
                    },
                },
            )
            assert mine["ok"] is True, mine
            theirs = await request(
                child, {"id": 2, "op": "notify_save", "persons": {"mamma": {"channels": []}}}
            )
            assert theirs["error"] == "forbidden"
            link = await request(
                child,
                {"id": 3, "op": "notify_save", "persons": {"sofia": {"ha_user_id": "u-x"}}},
            )
            assert link["error"] == "forbidden"
            await child.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_unknown_echo_or_phone_is_refused_and_nothing_is_saved() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            adult = await connect(client, ADULT_USER)
            bad_phone = await request(
                adult,
                {
                    "id": 1,
                    "op": "notify_save",
                    "persons": {"mamma": {"phone_notify": "mobile_app_x"}},
                },
            )
            assert bad_phone["error"] == "unknown_service"
            bad_echo = await request(
                adult,
                {
                    "id": 2,
                    "op": "notify_save",
                    "persons": {"mamma": {"alexa_notify": "media_player.garage"}},
                },
            )
            assert bad_echo["error"] == "unknown_service"
            assert "phone_notify" not in fake.config["persons"][1]
            assert "alexa_notify" not in fake.config["persons"][1]
            await adult.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_phone_test_is_asked_for_the_chosen_service_only() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        fake.config["persons"][1]["phone_notify"] = "mobile_app_mamma"
        ha_server, client, _ = await started(fake)
        try:
            adult = await connect(client, ADULT_USER)
            reply = await request(
                adult, {"id": 1, "op": "notify_test", "person": "mamma", "kind": "phone"}
            )
            assert reply == {"id": 1, "type": "result", "ok": True, "result": {"sent": 1}}
            (asked,) = fake.notify_tests
            assert asked["person"] == "mamma" and asked["kind"] == "phone"
            await adult.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_echo_test_covers_every_speaker_when_all_is_chosen() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        fake.config["persons"][1]["alexa_notify"] = "all"
        ha_server, client, _ = await started(fake)
        try:
            adult = await connect(client, ADULT_USER)
            reply = await request(
                adult, {"id": 1, "op": "notify_test", "person": "mamma", "kind": "alexa"}
            )
            assert reply["result"] == {"sent": 2}
            await adult.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_test_without_a_usable_service_says_so() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        fake.config["persons"][1]["phone_notify"] = "mobile_app_mamma"
        fake.notify_services.remove("mobile_app_mamma")  # the phone app was removed
        ha_server, client, _ = await started(fake)
        try:
            adult = await connect(client, ADULT_USER)
            reply = await request(
                adult, {"id": 1, "op": "notify_test", "person": "mamma", "kind": "phone"}
            )
            assert reply["error"] == "no_service"
            await adult.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_child_tests_only_own_and_guest_nothing() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        fake.config["persons"][0]["phone_notify"] = "mobile_app_sofia"
        ha_server, client, _ = await started(fake)
        try:
            child = await connect(client, CHILD_USER)
            other = await request(
                child, {"id": 1, "op": "notify_test", "person": "mamma", "kind": "phone"}
            )
            assert other["error"] == "forbidden"
            own = await request(
                child, {"id": 2, "op": "notify_test", "person": "sofia", "kind": "phone"}
            )
            assert own["result"] == {"sent": 1}
            await child.close()
            guest = await connect(client, GUEST_USER)
            denied = await request(
                guest, {"id": 3, "op": "notify_test", "person": "sofia", "kind": "phone"}
            )
            assert denied["error"] == "forbidden"
            await guest.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_echo_test_uses_the_speaker_and_volume_on_the_screen() -> None:
    """0.7.5: "Prova Echo" sends the speaker and the volume shown, saved or not."""

    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            adult = await connect(client, ADULT_USER)
            reply = await request(
                adult,
                {
                    "id": 1,
                    "op": "notify_test",
                    "person": "mamma",
                    "kind": "alexa",
                    "alexa_notify": "media_player.wohnzimmer",
                    "alexa_volume": 25,
                },
            )
            assert reply["result"] == {"sent": 1}
            sent = fake.notify_tests[-1]
            assert sent["alexa_notify"] == "media_player.wohnzimmer"
            assert sent["alexa_volume"] == 25
            await adult.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)
