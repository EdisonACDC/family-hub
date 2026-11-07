"""Runtime data types shared by the Family Hub modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry

from .storage import EventStore

if TYPE_CHECKING:
    from .calendar import FamilyHubCalendar
    from .external import ExternalManager
    from .reminders import ReminderManager


@dataclass
class FamilyHubData:
    """Runtime data attached to a loaded Family Hub config entry."""

    store: EventStore
    reminders: ReminderManager
    calendars: dict[str, FamilyHubCalendar] = field(default_factory=dict)
    external: ExternalManager | None = None


FamilyHubConfigEntry = ConfigEntry[FamilyHubData]
