"""Rubbish types for the tablet: a pickup's title becomes "Organico" with a flower.

The same rules as the integration's waste.py: the first type whose text is in the title (case
and umlauts ignored), else the type without a text ("Altro"). The integration keeps the
family's list; these defaults are used when it cannot say. A TrashCard on a dashboard can be
read and its types proposed.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

DEFAULT_WASTE_TYPES: list[dict[str, str]] = [
    {
        "id": "restmuell",
        "label": "Indifferenziato",
        "icon": "mdi:trash-can-outline",
        "pattern": "Restabfall, Restmüll",
        "color": "#9E9E9E",
    },
    {
        "id": "bio",
        "label": "Organico",
        "icon": "mdi:flower",
        "pattern": "Bioabfall, Bio",
        "color": "#8BC34A",
    },
    {
        "id": "gelb",
        "label": "Plastica",
        "icon": "mdi:recycle",
        "pattern": "Gelbe Tonne, Gelber Sack, Wertstoff",
        "color": "#FFC107",
    },
    {
        "id": "papier",
        "label": "Carta",
        "icon": "mdi:newspaper-variant",
        "pattern": "Papierabfall, Papier",
        "color": "#3F51B5",
    },
    {"id": "altro", "label": "Altro", "icon": "mdi:dump-truck", "pattern": "", "color": "#9C27B0"},
]

NAMED_COLORS = {
    "red": "#F44336",
    "pink": "#E91E63",
    "purple": "#9C27B0",
    "deep-purple": "#673AB7",
    "indigo": "#3F51B5",
    "blue": "#2196F3",
    "light-blue": "#03A9F4",
    "cyan": "#00BCD4",
    "teal": "#009688",
    "green": "#4CAF50",
    "light-green": "#8BC34A",
    "lime": "#CDDC39",
    "yellow": "#FFEB3B",
    "amber": "#FFC107",
    "orange": "#FF9800",
    "deep-orange": "#FF5722",
    "brown": "#795548",
    "grey": "#9E9E9E",
    "gray": "#9E9E9E",
    "blue-grey": "#607D8B",
    "black": "#000000",
    "white": "#FFFFFF",
}

# The TrashCard's own kinds, for a pattern entry that only says its type.
TRASHCARD_DEFAULTS = {
    "waste": ("Indifferenziato", "mdi:trash-can-outline", "#9E9E9E"),
    "organic": ("Organico", "mdi:flower", "#8BC34A"),
    "recycle": ("Plastica", "mdi:recycle", "#FFC107"),
    "paper": ("Carta", "mdi:newspaper-variant", "#3F51B5"),
    "others": ("Altro", "mdi:dump-truck", "#9C27B0"),
}

_HEX = re.compile(r"#[0-9A-Fa-f]{6}")


def plain(text: str) -> str:
    replaced = text.lower().replace("ß", "ss").replace("ä", "a").replace("ö", "o").replace("ü", "u")
    return unicodedata.normalize("NFKD", replaced).encode("ascii", "ignore").decode("ascii")


def _keys(pattern: str) -> list[str]:
    return [plain(part).strip() for part in re.split(r"[,|]", pattern) if part.strip()]


def type_of(title: str, types: list[dict[str, str]]) -> dict[str, str] | None:
    """The type of a pickup: the first whose text is in the title, else the catch-all."""
    text = plain(title)
    fallback = None
    for kind in types:
        keys = _keys(str(kind.get("pattern", "")))
        if not keys:
            fallback = fallback or kind
        elif any(key in text for key in keys):
            return kind
    return fallback


def waste_kind(title: str) -> str | None:
    """The id of the default type of a title."""
    kind = type_of(title, DEFAULT_WASTE_TYPES)
    return kind["id"] if kind else None


def color_of(value: Any, default: str = "#9C27B0") -> str:
    text = str(value or "").strip()
    if _HEX.fullmatch(text):
        return text.upper()
    return NAMED_COLORS.get(text.lower(), default)


def _trash_cards(node: Any) -> list[dict[str, Any]]:
    """Every custom:trash-card in a dashboard's configuration, however deep."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if node.get("type") == "custom:trash-card":
            found.append(node)
        for value in node.values():
            found.extend(_trash_cards(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_trash_cards(value))
    return found


def types_from_trashcard(dashboards: list[Any]) -> list[dict[str, str]]:
    """The rubbish types of the first TrashCard found: its "pattern" list (label, icon,
    pattern, color), or the older "settings" by kind. Empty if there is no TrashCard."""
    for config in dashboards:
        for card in _trash_cards(config):
            entries: list[tuple[str, dict[str, Any]]] = []
            if isinstance(card.get("pattern"), list):
                entries = [
                    (str(e.get("type") or "others"), e)
                    for e in card["pattern"]
                    if isinstance(e, dict)
                ]
            elif isinstance(card.get("settings"), dict):
                entries = [
                    (str(kind), e) for kind, e in card["settings"].items() if isinstance(e, dict)
                ]
            types: list[dict[str, str]] = []
            for kind, entry in entries:
                label, icon, color = TRASHCARD_DEFAULTS.get(kind, TRASHCARD_DEFAULTS["others"])
                types.append(
                    {
                        "id": "",
                        "label": str(entry.get("label") or label)[:30],
                        "icon": str(entry.get("icon") or icon),
                        "pattern": str(entry.get("pattern") or ""),
                        "color": color_of(entry.get("color"), color),
                    }
                )
            if types:
                return types
    return []
