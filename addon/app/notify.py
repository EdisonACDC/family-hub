"""Notification settings ("Avvisi") as the tablet shows them.

The add-on only reads what the page needs: the phone services and the Echo speakers that
exist now, and the people's settings. Sending, and every rule about which service a person
may use, is done by the integration (family_hub/notify/save and family_hub/notify/test).
"""

from __future__ import annotations

from typing import Any

PHONE_PREFIX = "mobile_app_"
ALEXA_PLATFORM = "alexa_media"
PERSON_CHANNELS = ["phone", "alexa", "tablet"]


def phone_services(domains: dict[str, Any]) -> list[str]:
    """Phone notify services of Home Assistant, by name without ``notify.``."""
    return sorted(n for n in domains.get("notify", {}) if n.startswith(PHONE_PREFIX))


def echo_speakers(entries: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Echo speakers: media players of the Alexa Media platform, from the entity registry."""
    speakers = [
        {
            "entity_id": e["entity_id"],
            "name": e.get("name") or e.get("original_name") or e["entity_id"],
        }
        for e in entries
        if e.get("platform") == ALEXA_PLATFORM and e["entity_id"].startswith("media_player.")
    ]
    return sorted(speakers, key=lambda s: s["entity_id"])


def settings_of(person: dict[str, Any]) -> dict[str, Any]:
    """The notification fields of one person, with defaults, as the page shows them."""
    return {
        "id": person["id"],
        "name": person["name"],
        "role": person.get("role", "guest"),
        "ha_user_id": person.get("ha_user_id") or "",
        "phone_notify": person.get("phone_notify") or "",
        "alexa_notify": person.get("alexa_notify") or "",
        "alexa_volume": person.get("alexa_volume"),
        "channels": list(person.get("channels", PERSON_CHANNELS)),
        "quiet_start": person.get("quiet_start") or "",
        "quiet_end": person.get("quiet_end") or "",
    }
