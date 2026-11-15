"""Web Push for the guest web app: VAPID keys and sending one message.

The keys are made once per family and kept in the guest store. pywebpush is the library
Home Assistant's own html5 integration uses; it is imported only when a message is sent, so a
family without guests never loads it. Subscriptions and keys are never logged.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from homeassistant.core import HomeAssistant

LOGGER = logging.getLogger(__name__)

# Push services of the browsers. A subscription that points anywhere else is refused, so a guest
# can never make Home Assistant send requests to another address (for example inside the home).
PUSH_HOSTS = (
    "fcm.googleapis.com",
    "android.googleapis.com",
    "updates.push.services.mozilla.com",
    "push.services.mozilla.com",
    "web.push.apple.com",
    "notify.windows.com",
    "push.apple.com",
)
MAX_ENDPOINT = 1024
# What a send returns when the subscription is gone and must be forgotten.
GONE = "gone"
SENT = "sent"
FAILED = "failed"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def generate_keys() -> dict[str, str]:
    """A new VAPID key pair: the raw private key and the public key the browser needs."""
    private = ec.generate_private_key(ec.SECP256R1())
    raw_private = private.private_numbers().private_value.to_bytes(32, "big")
    public = private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return {"private": _b64(raw_private), "public": _b64(public)}


def _push_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    return any(host == known or host.endswith("." + known) for known in PUSH_HOSTS)


def clean_subscription(raw: Any) -> dict[str, Any] | None:
    """The subscription a browser sent, if it is a real one of a known push service."""
    if not isinstance(raw, dict):
        return None
    endpoint = raw.get("endpoint")
    keys = raw.get("keys")
    if not isinstance(endpoint, str) or not isinstance(keys, dict) or len(endpoint) > MAX_ENDPOINT:
        return None
    parts = urlsplit(endpoint)
    if parts.scheme != "https" or not parts.hostname or parts.port not in (None, 443):
        return None
    if parts.username or parts.password or not _push_host(parts.hostname):
        return None
    p256dh, auth = keys.get("p256dh"), keys.get("auth")
    if not isinstance(p256dh, str) or not isinstance(auth, str):
        return None
    try:
        if len(_unb64(p256dh)) != 65 or not 8 <= len(_unb64(auth)) <= 32:
            return None
    except (ValueError, TypeError):
        return None
    return {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}


def _send_sync(
    subscription: dict[str, Any], payload: dict[str, Any], private_key: str, subject: str
) -> str:
    from py_vapid import Vapid  # noqa: PLC0415 - loaded only when a message goes out
    from pywebpush import WebPushException, webpush  # noqa: PLC0415

    vapid = Vapid.from_raw(private_key.encode("ascii"))
    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload),
            vapid_private_key=vapid,
            vapid_claims={"sub": subject},
            ttl=3600,
            timeout=10,
        )
    except WebPushException as err:
        status = getattr(getattr(err, "response", None), "status_code", None)
        if status in (404, 410):
            return GONE
        LOGGER.warning("Family Hub guest push not delivered (status %s)", status)
        return FAILED
    except Exception as err:  # noqa: BLE001 - a network error must never break Family Hub
        LOGGER.warning("Family Hub guest push not delivered: %s", type(err).__name__)
        return FAILED
    return SENT


async def async_send(
    hass: HomeAssistant,
    subscription: dict[str, Any],
    payload: dict[str, Any],
    private_key: str,
    subject: str,
) -> str:
    """Send one message. Returns SENT, GONE (forget the subscription) or FAILED."""
    return await hass.async_add_executor_job(
        _send_sync, subscription, payload, private_key, subject
    )
