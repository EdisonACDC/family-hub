"""A shared screen is saved by an adult and then takes effect: its user is shared, an admin
who is no person is an adult, and a user who is neither stays a guest."""

from __future__ import annotations

import asyncio

from tests.fake_ha import ADMIN_USER, FakeHA
from tests.helpers import ADULT_USER, GUEST_USER, connect, request, shutdown, started


def test_shared_screen_is_saved_and_takes_effect() -> None:
    async def scenario() -> None:
        fake = FakeHA()
        ha_server, client, _ = await started(fake)
        try:
            adult = await connect(client, ADULT_USER)
            saved = await request(adult, {"id": 1, "op": "shared_save", "users": ["u-stranger"]})
            assert saved["ok"] is True
            assert fake.config["shared_users"] == ["u-stranger"]
            await adult.close()

            shared = await connect(client, "u-stranger")
            identity = (await request(shared, {"id": 2, "op": "identity"}))["result"]
            assert identity["role"] == "shared"
            await shared.close()

            admin = await connect(client, ADMIN_USER)
            identity = (await request(admin, {"id": 3, "op": "identity"}))["result"]
            assert identity["role"] == "adult"
            await admin.close()

            guest = await connect(client, GUEST_USER)
            identity = (await request(guest, {"id": 4, "op": "identity"}))["result"]
            assert identity["role"] == "guest"
            await guest.close()
        finally:
            await shutdown(ha_server, client)

    asyncio.run(scenario())
