"""Sharing (invites for the grandparents) through the add-on: adults only, checked types, and the
guest event followed only once invites are used."""

from __future__ import annotations

import asyncio
from typing import Any

from tests.fake_ha import FakeHA
from tests.helpers import ADULT_USER, CHILD_USER, GUEST_USER, connect, request, shutdown, started

INVITE = {"name": "Nonna Èlia 👵", "persons": ["sofia"], "categories": ["scuola"]}


def _run(scenario: Any) -> None:
    asyncio.run(scenario())


def _guest_subscriptions(fake: FakeHA) -> int:
    return sum(
        1
        for _, kind, wanted in fake._subs.values()
        if kind == "events" and wanted == "family_hub_guest_changed"
    )


def test_only_adults_reach_sharing() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            for user in (CHILD_USER, GUEST_USER, None):
                ws = await connect(client, user)
                for n, op in enumerate(
                    ("share_get", "share_invite_create", "share_device_disable")
                ):
                    answer = await request(
                        ws, {"id": n + 1, "op": op, "invite": INVITE, "device_id": "x"}
                    )
                    assert answer == {
                        "type": "result",
                        "id": n + 1,
                        "ok": False,
                        "error": "forbidden",
                    }
                await ws.close()
            assert fake.guest_calls == []
            ws = await connect(client, ADULT_USER)
            answer = await request(ws, {"id": 1, "op": "share_invite_create", "invite": INVITE})
            assert answer["ok"] and "#i=" in answer["result"]["link"]
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_fields_are_checked_before_home_assistant() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, ADULT_USER)
            for n, payload in enumerate(
                (
                    {"op": "share_invite_create", "invite": "Nonna"},
                    {"op": "share_device_confirm", "device_id": "x", "accept": "yes"},
                    {"op": "share_pending_decide", "pending_id": 5, "accept": True},
                    {
                        "op": "share_pending_decide",
                        "pending_id": "p",
                        "accept": True,
                        "changes": "x",
                    },
                    {"op": "share_device_update", "device_id": "x"},
                )
            ):
                answer = await request(ws, {"id": n + 1, **payload})
                assert answer["ok"] is False and answer["error"] == "bad_request", payload
            assert fake.guest_calls == []
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_the_guest_event_is_followed_only_when_invites_exist() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, ADULT_USER)
            assert (await request(ws, {"id": 1, "op": "share_get"}))["ok"]
            await asyncio.sleep(0.1)
            assert _guest_subscriptions(fake) == 0  # nothing shared: as in 0.8
            await request(ws, {"id": 2, "op": "share_invite_create", "invite": INVITE})
            await asyncio.sleep(0.1)
            assert _guest_subscriptions(fake) == 1
            # A change reaches the adult's page.
            await fake.guest_changed()
            for _ in range(10):
                msg = await ws.receive_json(timeout=5)
                if msg.get("type") == "guest_changed":
                    break
            else:
                raise AssertionError("no guest_changed message")
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_events_carry_who_added_them() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        fake.guest["pending"] = [
            {
                "id": "p1",
                "device": "Nonna Èlia 👵",
                "created_at": "2026-11-15T09:00:00+00:00",
                "title": "Merenda",
                "start": "2026-11-20T16:00:00+01:00",
                "end": "2026-11-20T17:00:00+01:00",
                "all_day": False,
                "category": "scuola",
                "persons": ["sofia"],
                "location": "",
                "note": "",
            }
        ]
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, ADULT_USER)
            answer = await request(
                ws, {"id": 1, "op": "share_pending_decide", "pending_id": "p1", "accept": True}
            )
            assert answer["ok"] and answer["result"]["pending"] == []
            events = await request(
                ws,
                {
                    "id": 2,
                    "op": "events",
                    "start": "2026-11-16 00:00:00",
                    "end": "2026-11-30 00:00:00",
                },
            )
            school = [
                e for items in events["result"].values() for e in items if e["summary"] == "Merenda"
            ]
            assert school and school[0]["added_by"] == "Nonna Èlia 👵"
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_outside_the_supervisor_there_is_no_panel_address(monkeypatch: Any) -> None:
    from app.server import own_panel

    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    assert asyncio.run(own_panel()) is None
