"""External sources: only the entities the guide chose can be used; to-do lists follow the
roles; external calendars are read only."""

from __future__ import annotations

import asyncio
from typing import Any

from tests.fake_ha import SHOP, WASTE, WEATHER, FakeHA
from tests.helpers import ADULT_USER, CHILD_USER, GUEST_USER, connect, request, shutdown, started


def _run(scenario: Any) -> None:
    asyncio.run(scenario())


def test_only_chosen_entities_can_be_used() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, ADULT_USER)
            # A to-do list that exists but was not chosen in the guide.
            fake.todo_items["todo.lavoro"] = [
                {"uid": "x", "summary": "X", "status": "needs_action"}
            ]
            other = await request(ws, {"id": 1, "op": "todo_items", "entity_id": "todo.lavoro"})
            assert other == {"id": 1, "type": "result", "ok": False, "error": "forbidden"}
            chosen = await request(ws, {"id": 2, "op": "todo_items", "entity_id": SHOP})
            assert chosen["ok"] is True
            assert [i["summary"] for i in chosen["result"]] == ["Latte", "Pane"]
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_guests_read_lists_but_cannot_change_them() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, GUEST_USER)
            assert (await request(ws, {"id": 1, "op": "todo_items", "entity_id": SHOP}))["ok"]
            add = await request(
                ws, {"id": 2, "op": "todo_add", "entity_id": SHOP, "summary": "Uova"}
            )
            assert add["error"] == "forbidden"
            assert fake.calls == []
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_children_add_and_tick_but_cannot_remove() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, CHILD_USER)
            add = await request(
                ws, {"id": 1, "op": "todo_add", "entity_id": SHOP, "summary": "Uova"}
            )
            assert add["ok"] is True
            tick = await request(
                ws, {"id": 2, "op": "todo_update", "entity_id": SHOP, "item": "latte", "done": True}
            )
            assert tick["ok"] is True
            remove = await request(
                ws, {"id": 3, "op": "todo_remove", "entity_id": SHOP, "item": "pane"}
            )
            assert remove == {"id": 3, "type": "result", "ok": False, "error": "forbidden"}
            assert [c["service"] for c in fake.calls] == ["add_item", "update_item"]
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_adults_remove_items() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, ADULT_USER)
            remove = await request(
                ws, {"id": 1, "op": "todo_remove", "entity_id": SHOP, "item": "pane"}
            )
            assert remove["ok"] is True
            assert [i["uid"] for i in fake.todo_items[SHOP]] == ["latte"]
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_only_adults_see_the_list_of_candidates() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, ADULT_USER)
            reply = await request(ws, {"id": 1, "op": "entities"})
            ids = sorted(e["entity_id"] for e in reply["result"])
            assert ids == sorted([SHOP, WASTE, WEATHER])
            await ws.close()
            child = await connect(client, CHILD_USER)
            assert (await request(child, {"id": 2, "op": "entities"}))["ok"] is False
            await child.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_external_calendar_is_read_only_for_everyone() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            child = await connect(client, CHILD_USER)
            reply = await request(
                child,
                {
                    "id": 1,
                    "op": "events",
                    "start": "2027-01-01 00:00:00",
                    "end": "2027-02-01 00:00:00",
                },
            )
            waste = reply["result"][WASTE]
            assert [e["summary"] for e in waste] == ["Ritiro indifferenziato"]
            assert waste[0]["external"] is True
            # Family actions cannot touch it: its id is not a family record.
            record = fake.events[WASTE][0]["record_id"]
            change = await request(
                child,
                {"id": 2, "op": "service", "service": "delete_event", "data": {"uid": record}},
            )
            assert change["ok"] is False and change["error"] == "not_found"
            assert fake.calls == []
            await child.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)
