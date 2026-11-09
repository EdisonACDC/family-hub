"""Which phones and Echo speakers a person may be notified on.

Phones are ``notify.mobile_app_*`` services. Echo speakers are ``media_player`` entities of the
Alexa Media Player platform (``alexa_media``), read from the entity registry. Announcements go
through ``notify.alexa_media`` with the chosen speakers as targets. A person can only be given
what exists right now, so the guide and the "Avvisi" page offer lists, never free text.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import ALEXA_ALL, ALEXA_PLATFORM, ECHO_NOT_SPEAKER_NAMES, PHONE_SERVICE_PREFIX

UNREADY_STATES = ("unavailable", "unknown")


def is_echo_speaker(hass: HomeAssistant, entity_id: str, original_name: str | None) -> bool:
    """A real Echo that is enabled and reachable: not the multiroom group, a Fire TV or the Alexa
    app on this device, and not unavailable."""
    state = hass.states.get(entity_id)
    if state is None or state.state in UNREADY_STATES:
        return False
    friendly = str(state.attributes.get("friendly_name") or "")
    name = f"{entity_id} {original_name or ''} {friendly}".lower().replace("_", " ")
    return not any(part in name for part in ECHO_NOT_SPEAKER_NAMES)


def echo_entities(hass: HomeAssistant) -> list[str]:
    """Entity ids of the Echo speakers: media players of the Alexa Media platform that are enabled,
    available and real speakers."""
    registry = er.async_get(hass)
    return sorted(
        entry.entity_id
        for entry in registry.entities.values()
        if entry.platform == ALEXA_PLATFORM
        and entry.domain == "media_player"
        and entry.disabled_by is None
        and is_echo_speaker(hass, entry.entity_id, entry.original_name)
    )


def available_services(hass: HomeAssistant) -> dict[str, list[str]]:
    """What exists now: phone notify services (names without ``notify.``) and Echo entities."""
    names = sorted(hass.services.async_services().get("notify", {}))
    return {
        "phone": [n for n in names if n.startswith(PHONE_SERVICE_PREFIX)],
        "alexa": echo_entities(hass),
    }


def alexa_targets(hass: HomeAssistant, choice: str) -> list[str]:
    """The Echo speakers one person's announcements go to right now."""
    speakers = echo_entities(hass)
    if choice == ALEXA_ALL:
        return speakers
    return [choice] if choice in speakers else []
