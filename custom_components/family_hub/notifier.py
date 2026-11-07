"""Send reminders and summaries to phones (notify), speakers (tts) and the wall tablet.

Every call goes through Home Assistant services. A missing service is logged and skipped,
never raised. Message text is never logged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later

from .const import ECHO_RESTORE_SECONDS, EVENT_REMINDER, EVENT_REMINDER_CLOSED, PERSON_CHANNELS
from .notify_settings import alexa_targets

LOGGER = logging.getLogger(__name__)

# The text of a test message from the "Avvisi" page.
TEST_MESSAGE = "Prova: questo è un avviso di prova di Family Hub."

# Notification texts, shown on phones and tablets. Keys are language codes.
TEXTS: dict[str, dict[str, str]] = {
    "it": {
        "reminder": "Promemoria",
        "summary_morning": "Oggi in famiglia",
        "summary_evening": "Domani in famiglia",
        "all_day": "Tutto il giorno",
        "tomorrow": "domani",
        "nothing": "Nessun evento",
        "done": "Fatto",
        "dismiss": "Ferma",
        "snooze_10": "Posticipa 10 min",
        "snooze_60": "Posticipa 1 ora",
    },
    "de": {
        "reminder": "Erinnerung",
        "summary_morning": "Heute in der Familie",
        "summary_evening": "Morgen in der Familie",
        "all_day": "Ganztägig",
        "tomorrow": "morgen",
        "nothing": "Keine Termine",
        "done": "Erledigt",
        "dismiss": "Stopp",
        "snooze_10": "10 Min. später",
        "snooze_60": "1 Stunde später",
    },
    "en": {
        "reminder": "Reminder",
        "summary_morning": "Today in the family",
        "summary_evening": "Tomorrow in the family",
        "all_day": "All day",
        "tomorrow": "tomorrow",
        "nothing": "No events",
        "done": "Done",
        "dismiss": "Dismiss",
        "snooze_10": "Snooze 10 min",
        "snooze_60": "Snooze 1 hour",
    },
}


def texts_for(language: str) -> dict[str, str]:
    """Return the notification texts for a language, English if unknown."""
    return TEXTS.get(language, TEXTS["en"])


def reminder_actions(uid: str, text: dict[str, str]) -> list[dict[str, str]]:
    """Buttons for a phone reminder. The ids are parsed in reminders.py."""
    return [
        {"action": f"FH_DONE_{uid}", "title": text["done"]},
        {"action": f"FH_DISMISS_{uid}", "title": text["dismiss"]},
        {"action": f"FH_SNOOZE_10_{uid}", "title": text["snooze_10"]},
        {"action": f"FH_SNOOZE_60_{uid}", "title": text["snooze_60"]},
    ]


@dataclass(frozen=True)
class Target:
    """A person who may receive a notification right now."""

    name: str
    phone_notify: str | None
    speaker: str | None
    alexa_notify: str | None
    quiet: bool
    # Channels this person accepts: "phone", "alexa", "tablet" (see PERSON_CHANNELS).
    channels: frozenset[str] = frozenset(PERSON_CHANNELS)
    # Announce volume on Echo speakers, 0-100, or None for the speaker's own level.
    alexa_volume: int | None = None


@dataclass(frozen=True)
class Delivery:
    """One notification to send to the given targets on the enabled channels."""

    title: str
    message: str
    notification_id: str
    targets: list[Target]
    channels: frozenset[str]
    tts_entity: str | None
    tablet: bool
    actions: list[dict[str, str]] = field(default_factory=list)
    uid: str = ""


async def _call(hass: HomeAssistant, domain: str, service: str, data: dict[str, Any]) -> None:
    if not hass.services.has_service(domain, service):
        LOGGER.warning("Reminder not sent: %s.%s is not available", domain, service)
        return
    await hass.services.async_call(domain, service, data, blocking=False)


async def announce_on_echos(
    hass: HomeAssistant, speakers: list[str], message: str, volume: int | None
) -> None:
    """Announce on Echo speakers through notify.alexa_media.

    With a volume chosen: each speaker's volume is set first, then the announcement is made,
    then the volume each speaker had is put back after a few seconds. The old volume is put
    back only when it was known. Without a volume, nothing else changes.
    """
    if not speakers:
        return
    if not hass.services.has_service("notify", "alexa_media"):
        LOGGER.warning("Announcement not sent: notify.alexa_media is not available")
        return
    previous: dict[str, float] = {}
    if volume is not None:
        for speaker in speakers:
            state = hass.states.get(speaker)
            level = state.attributes.get("volume_level") if state else None
            if isinstance(level, int | float):
                previous[speaker] = float(level)
            await hass.services.async_call(
                "media_player",
                "volume_set",
                {"entity_id": speaker, "volume_level": volume / 100},
                blocking=True,
            )
    await hass.services.async_call(
        "notify",
        "alexa_media",
        {"message": message, "target": speakers, "data": {"type": "announce"}},
        blocking=True,
    )
    if previous:

        async def _restore(_now: datetime) -> None:
            for speaker, level in previous.items():
                await hass.services.async_call(
                    "media_player",
                    "volume_set",
                    {"entity_id": speaker, "volume_level": level},
                    blocking=False,
                )

        async_call_later(hass, ECHO_RESTORE_SECONDS, _restore)


async def async_send(hass: HomeAssistant, delivery: Delivery) -> None:
    """Send on every enabled channel, to the people who accept that channel."""
    seen: set[str] = set()  # one message per service or speaker, even if shared
    if "phone" in delivery.channels:
        for target in delivery.targets:
            if "phone" not in target.channels:
                continue
            if target.phone_notify and f"phone:{target.phone_notify}" not in seen:
                seen.add(f"phone:{target.phone_notify}")
                data: dict[str, Any] = {"tag": delivery.notification_id}
                if delivery.actions:
                    data["actions"] = delivery.actions
                await _call(
                    hass,
                    "notify",
                    target.phone_notify,
                    {"title": delivery.title, "message": delivery.message, "data": data},
                )
    if "speaker" in delivery.channels:
        for target in delivery.targets:
            if "alexa" not in target.channels:
                continue
            # Alexa announce is preferred when the person has an Alexa notify service.
            if target.alexa_notify:
                speakers = [
                    s for s in alexa_targets(hass, target.alexa_notify) if f"echo:{s}" not in seen
                ]
                seen.update(f"echo:{s}" for s in speakers)
                await announce_on_echos(hass, speakers, delivery.message, target.alexa_volume)
            elif target.speaker and delivery.tts_entity:
                if f"speaker:{target.speaker}" in seen:
                    continue
                seen.add(f"speaker:{target.speaker}")
                await _call(
                    hass,
                    "tts",
                    "speak",
                    {
                        "entity_id": delivery.tts_entity,
                        "media_player_entity_id": target.speaker,
                        "message": delivery.message,
                    },
                )
    if "tablet" in delivery.channels and delivery.tablet:
        await _call(
            hass,
            "persistent_notification",
            "create",
            {
                "title": delivery.title,
                "message": delivery.message,
                "notification_id": delivery.notification_id,
            },
        )
        # The tablet add-on shows its own popup from this event (see addon/).
        hass.bus.async_fire(
            EVENT_REMINDER,
            {
                "uid": delivery.uid,
                "title": delivery.title,
                "message": delivery.message,
                "notification_id": delivery.notification_id,
            },
        )
    # browser_mod is optional (HACS): without it the service does not exist and nothing is
    # sent, quietly.
    if (
        "popup" in delivery.channels
        and delivery.tablet
        and hass.services.has_service("browser_mod", "popup")
    ):
        await hass.services.async_call(
            "browser_mod",
            "popup",
            {
                "title": delivery.title,
                "content": delivery.message,
                "dismissable": True,
            },
            blocking=False,
        )


async def async_dismiss(hass: HomeAssistant, notification_id: str, uid: str) -> None:
    """Remove a tablet popup and tell the tablet add-on to close its own."""
    await _call(hass, "persistent_notification", "dismiss", {"notification_id": notification_id})
    hass.bus.async_fire(EVENT_REMINDER_CLOSED, {"uid": uid, "notification_id": notification_id})
