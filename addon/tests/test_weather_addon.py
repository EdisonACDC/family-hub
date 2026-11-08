"""Weather in the add-on: the entity the guide chose, read only, for everyone; its daily
forecast from weather/subscribe_forecast."""

from __future__ import annotations

import asyncio
from typing import Any

from tests.fake_ha import WEATHER, FakeHA
from tests.helpers import ADULT_USER, CHILD_USER, GUEST_USER, connect, request, shutdown, started


def _run(scenario: Any) -> None:
    asyncio.run(scenario())


def test_everyone_reads_the_chosen_weather_with_its_forecast() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            for user in (ADULT_USER, CHILD_USER, GUEST_USER):
                ws = await connect(client, user)
                reply = await request(ws, {"id": 1, "op": "weather"})
                assert reply["ok"] is True, reply
                result = reply["result"]
                assert result["entity_id"] == WEATHER
                assert result["condition"] == "cloudy"
                assert result["temperature"] == 5 and result["unit"] == "°C"
                assert len(result["forecast"]) == 5
                assert result["forecast"][0]["templow"] == 2.0
                await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_no_chosen_weather_gives_nothing() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        fake.config["sources"]["weather"] = []
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, ADULT_USER)
            reply = await request(ws, {"id": 1, "op": "weather"})
            assert reply == {"id": 1, "type": "result", "ok": True, "result": None}
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)


def test_weather_is_read_only_for_the_add_on() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, ADULT_USER)
            # Writing through the weather command is not a thing: only reads are offered.
            reply = await request(ws, {"id": 2, "op": "weather_save", "entity_id": WEATHER})
            assert reply["ok"] is False
            await ws.close()
        finally:
            await shutdown(ha_server, client)

    _run(scenario)
