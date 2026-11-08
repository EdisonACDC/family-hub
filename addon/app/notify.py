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


PHONE_WORDS = {"iphone": "iPhone", "ipad": "iPad", "ios": "iOS"}


def phone_label(name: str) -> str:
    """A readable name for a phone service: mobile_app_iphone_luca -> "iPhone Luca"."""
    words = name.removeprefix(PHONE_PREFIX).replace("_", " ").split()
    return " ".join(PHONE_WORDS.get(w.lower(), w.capitalize()) for w in words) or name


def phone_services(domains: dict[str, Any]) -> list[dict[str, str]]:
    """Phone notify services: the name without ``notify.`` and a readable label, sorted."""
    names = [n for n in domains.get("notify", {}) if n.startswith(PHONE_PREFIX)]
    services = [{"name": n, "label": phone_label(n)} for n in names]
    return sorted(services, key=lambda s: (s["label"].lower(), s["name"]))


def echo_speakers(
    entries: list[dict[str, Any]], states: list[dict[str, Any]] | None = None
) -> list[dict[str, str]]:
    """Echo speakers: media players of the Alexa Media platform.

    The name is the friendly name the speaker has in Home Assistant; the registry name is
    the fallback, and the entity id the last resort.
    """
    friendly = {s["entity_id"]: s.get("attributes", {}).get("friendly_name") for s in states or []}
    speakers = [
        {
            "entity_id": e["entity_id"],
            "name": friendly.get(e["entity_id"])
            or e.get("name")
            or e.get("original_name")
            or e["entity_id"],
        }
        for e in entries
        if e.get("platform") == ALEXA_PLATFORM and e["entity_id"].startswith("media_player.")
    ]
    return sorted(speakers, key=lambda s: (s["name"].lower(), s["entity_id"]))


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
