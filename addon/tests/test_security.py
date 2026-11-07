"""Who may reach the add-on, and what each role may do."""

from __future__ import annotations

import asyncio
from typing import Any

from aiohttp.test_utils import TestClient, TestServer
from app.ha_link import HAClient
from app.server import create_app

from tests.fake_ha import FAMILY, FakeHA
from tests.helpers import ADULT_USER, CHILD_USER, GUEST_USER, connect, request, shutdown, started


def _run(scenario: Any) -> None:
    asyncio.run(scenario())


async def _outside_client(fake: FakeHA) -> tuple[TestServer, TestClient]:
    """An add-on that only accepts the Ingress proxy at 10.9.9.9, so this test client is outside."""
    ha_server = TestServer(fake.app)
    await ha_server.start_server()
    ha = HAClient(str(ha_server.make_url("/api/websocket")), "test-token")
    client = TestClient(TestServer(create_app(ha, frozenset({"10.9.9.9"}))))
    await client.start_server()
    return ha_server, client


async def _seed(fake: FakeHA) -> tuple[str, str]:
    """One event for mamma and one for sofia. Returns their record ids."""
    await fake.add_event(
        FAMILY, "Riunione", "2026-11-10T09:00:00+01:00", "2026-11-10T10:00:00+01:00", "mamma"
    )
    await fake.add_event(
        FAMILY, "Recita", "2026-11-11T17:00:00+01:00", "2026-11-11T18:00:00+01:00", "sofia"
    )
    mamma, sofia = fake.events[FAMILY]
    return mamma["record_id"], sofia["record_id"]


def test_requests_from_outside_the_ingress_proxy_get_403() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client = await _outside_client(fake)
        try:
            response = await client.get("/")
            assert response.status == 403
            response = await client.get("/static/app.js")
            assert response.status == 403
            response = await client.get("/ws")
            assert response.status == 403
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_ingress_proxy_is_served() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            response = await client.get("/")
            assert response.status == 200
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_identity_is_reported_from_the_user_header() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            for user, role, person in [
                (ADULT_USER, "adult", "mamma"),
                (CHILD_USER, "child", "sofia"),
                (GUEST_USER, "guest", "ospite"),
                (None, "guest", None),
                ("u-stranger", "guest", None),
            ]:
                ws = await client.ws_connect(
                    "/ws", headers={"X-Remote-User-Id": user} if user else {}
                )
                first = await ws.receive_json(timeout=5)
                assert first == {"type": "identity", "role": role, "person_id": person}
                await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_child_sees_only_events_they_take_part_in() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        await _seed(fake)
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, CHILD_USER)
            reply = await request(
                ws,
                {
                    "id": 1,
                    "op": "events",
                    "start": "2026-11-09 00:00:00",
                    "end": "2026-11-16 00:00:00",
                },
            )
            assert [e["summary"] for e in reply["result"][FAMILY]] == ["Recita"]
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_adult_and_guest_see_every_event() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        await _seed(fake)
        ha_server, client, _ = await started(fake)
        try:
            for user in (ADULT_USER, GUEST_USER):
                ws = await connect(client, user)
                reply = await request(
                    ws,
                    {
                        "id": 1,
                        "op": "events",
                        "start": "2026-11-09 00:00:00",
                        "end": "2026-11-16 00:00:00",
                    },
                )
                assert len(reply["result"][FAMILY]) == 2
                await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_child_add_event_is_forced_to_the_child() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, CHILD_USER)
            reply = await request(
                ws,
                {
                    "id": 2,
                    "op": "service",
                    "service": "add_event",
                    "data": {
                        "category": "famiglia",
                        "summary": "Allenamento",
                        "start": "2026-11-12 16:00:00",
                        "persons": ["mamma", "papa"],
                    },
                },
            )
            assert reply["ok"] is True
            (call,) = [c for c in fake.calls if c["service"] == "add_event"]
            assert call["data"]["persons"] == ["sofia"]
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_child_can_change_own_event_but_not_others() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        mamma_uid, sofia_uid = await _seed(fake)
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, CHILD_USER)
            denied = await request(
                ws,
                {"id": 3, "op": "service", "service": "delete_event", "data": {"uid": mamma_uid}},
            )
            assert denied == {"id": 3, "type": "result", "ok": False, "error": "forbidden"}
            allowed = await request(
                ws,
                {
                    "id": 4,
                    "op": "service",
                    "service": "update_event",
                    "data": {"uid": sofia_uid, "summary": "Recita (prova)"},
                },
            )
            assert allowed["ok"] is True
            assert [c["service"] for c in fake.calls] == ["update_event"]
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_child_cannot_hand_an_event_to_other_persons() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        _, sofia_uid = await _seed(fake)
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, CHILD_USER)
            reply = await request(
                ws,
                {
                    "id": 5,
                    "op": "service",
                    "service": "update_event",
                    "data": {"uid": sofia_uid, "persons": ["mamma"]},
                },
            )
            assert reply["ok"] is False
            assert fake.calls == []
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_guest_is_read_only() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        mamma_uid, _ = await _seed(fake)
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, GUEST_USER)
            for n, payload in enumerate(
                [
                    {
                        "op": "service",
                        "service": "add_event",
                        "data": {"category": "famiglia", "summary": "X", "start": "2026-11-12"},
                    },
                    {"op": "service", "service": "stop_reminder", "data": {"uid": mamma_uid}},
                ],
                start=6,
            ):
                reply = await request(ws, {"id": n, **payload})
                assert reply["ok"] is False and reply["error"] == "forbidden"
            assert fake.calls == []
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_user_without_a_person_is_read_only() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, None)
            reply = await request(
                ws,
                {
                    "id": 9,
                    "op": "service",
                    "service": "add_event",
                    "data": {"category": "famiglia", "summary": "X", "start": "2026-11-12"},
                },
            )
            assert reply["ok"] is False
            assert fake.calls == []
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_child_gets_only_reminders_of_their_own_events() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        mamma_uid, sofia_uid = await _seed(fake)
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, CHILD_USER)
            await fake.push_event("family_hub_reminder", {"uid": mamma_uid, "message": "mamma"})
            await fake.push_event("family_hub_reminder", {"uid": sofia_uid, "message": "sofia"})
            msg = await ws.receive_json(timeout=5)
            assert msg["data"]["message"] == "sofia"
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_guests_get_no_reminder_popups() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        mamma_uid, _ = await _seed(fake)
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, GUEST_USER)
            await fake.push_event("family_hub_reminder", {"uid": mamma_uid, "message": "x"})
            await asyncio.sleep(0.3)
            await ws.send_json({"id": 1, "op": "calendars"})
            msg = await ws.receive_json(timeout=5)
            assert msg["type"] == "result"  # the next message is the reply, no popup before it
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)
