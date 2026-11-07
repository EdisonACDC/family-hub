"""Persistent event storage for Family Hub.

Events live in the integration's own storage file (Home Assistant `.storage`),
so the add-on or any external calendar is never required.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_VERSION

Listener = Callable[[], Awaitable[None]]


class EventStore:
    """Holds all events of one Family Hub config entry, keyed by uid.

    Event record (JSON-serialisable)::

        {
            "uid": str, "category": str, "summary": str,
            "description": str, "location": str, "persons": [str],
            "start": ISO string, "end": ISO string, "all_day": bool,
            "reminder_offsets": [int] | None,  # minutes before start; None = family default
            "reminders_off": bool,             # set by "Fatto" / stop_reminder
        }
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.events"
        )
        self.events: dict[str, dict[str, Any]] = {}
        self._listeners: list[Listener] = []

    async def async_load(self) -> None:
        """Load events from disk."""
        data = await self._store.async_load()
        if data is not None:
            self.events = dict(data.get("events", {}))

    def add_listener(self, listener: Listener) -> Callable[[], None]:
        """Run ``listener`` after every save. Returns a function that removes it."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    async def async_save(self) -> None:
        """Persist events to disk, then tell the listeners (reminders) to refresh."""
        await self._store.async_save({"events": self.events})
        for listener in list(self._listeners):
            await listener()
