"""Rubbish kinds, recognised from a pickup's title (the same rules as the integration's
external.py: lower case, umlauts written out, substring match). The colours are defaults;
the family can change them, and the integration keeps the changes."""

from __future__ import annotations

import unicodedata
from typing import Any

WASTE_KINDS: dict[str, dict[str, Any]] = {
    "restmuell": {
        "keys": ["restmull", "restabfall"],
        "label": "Restmüll",
        "color": "#374151",
        "icon": "trash",
    },
    "bio": {"keys": ["bio"], "label": "Bio", "color": "#8B5A2B", "icon": "leaf"},
    "papier": {"keys": ["papier"], "label": "Papier", "color": "#2563EB", "icon": "paper"},
    "gelb": {
        "keys": ["gelb", "wertstoff"],
        "label": "Gelber Sack",
        "color": "#EAB308",
        "icon": "bag",
    },
    "glas": {"keys": ["glas"], "label": "Glas", "color": "#16A34A", "icon": "bottle"},
}


def plain(text: str) -> str:
    replaced = text.lower().replace("ß", "ss").replace("ä", "a").replace("ö", "o").replace("ü", "u")
    return unicodedata.normalize("NFKD", replaced).encode("ascii", "ignore").decode("ascii")


def waste_kind(title: str) -> str | None:
    """The rubbish kind named in a title, or None."""
    text = plain(title)
    for kind, info in WASTE_KINDS.items():
        if any(key in text for key in info["keys"]):
            return kind
    return None
