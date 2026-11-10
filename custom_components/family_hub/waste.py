"""Rubbish types: how a pickup's title becomes "Organico" with a flower, as in the TrashCard.

Each type has an id, a label, a Material Design icon ("mdi:flower"), the texts to look for in
the title (comma separated, case and umlauts ignored) and a colour. A type with no text to look
for takes every pickup that matches no other type ("Altro"). The family can change the list; it
applies to the rubbish calendars from ICS files and from Home Assistant alike.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

OPT_WASTE_TYPES = "waste_types"
MAX_TYPES = 12

# The same rubbish types in every language: the id, icon and colour are shared, the label and
# the texts to look for are not. The family's language picks the list (English if unknown).
_SHARED_KINDS = [
    ("restmuell", "mdi:trash-can-outline", "#9E9E9E"),
    ("bio", "mdi:flower", "#8BC34A"),
    ("gelb", "mdi:recycle", "#FFC107"),
    ("papier", "mdi:newspaper-variant", "#3F51B5"),
    ("glas", "mdi:bottle-wine-outline", "#009688"),
    ("altro", "mdi:dump-truck", "#9C27B0"),
]
_LABELS: dict[str, list[tuple[str, str]]] = {
    "it": [
        ("Indifferenziato", "Indifferenziat, Secco, Residuo"),
        ("Organico", "Organico, Umido, Frazione organica"),
        ("Plastica", "Plastica, Multimateriale, Imballaggi"),
        ("Carta", "Carta, Cartone"),
        ("Vetro", "Vetro"),
        ("Altro", ""),
    ],
    "de": [
        ("Restmüll", "Restabfall, Restmüll"),
        ("Biomüll", "Bioabfall, Biomüll, Bio"),
        ("Gelbe Tonne", "Gelbe Tonne, Gelber Sack, Wertstoff"),
        ("Papier", "Papierabfall, Papier"),
        ("Glas", "Glas, Glascontainer"),
        ("Sonstiges", ""),
    ],
    "en": [
        ("General waste", "General waste, Residual, Rubbish, Black bin"),
        ("Food waste", "Food waste, Organic, Compost, Green bin"),
        ("Recycling", "Recycling, Plastic, Packaging, Yellow bin"),
        ("Paper", "Paper, Cardboard"),
        ("Glass", "Glass"),
        ("Other", ""),
    ],
}


def _kinds_for(language: str) -> list[dict[str, str]]:
    labels = _LABELS.get(language, _LABELS["en"])
    return [
        {"id": kind_id, "label": label, "icon": icon, "pattern": pattern, "color": color}
        for (kind_id, icon, color), (label, pattern) in zip(_SHARED_KINDS, labels, strict=True)
    ]


def default_waste_types(language: str) -> list[dict[str, str]]:
    """The default rubbish types in the family's language ("it", "de" or "en")."""
    return _kinds_for(language)


# Home Assistant's named colours, as a TrashCard may use them ("light-green").
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

_HEX = re.compile(r"#[0-9A-Fa-f]{6}")
_ICON = re.compile(r"mdi:[a-z0-9-]{1,60}")


class WasteTypeError(ValueError):
    """A type that cannot be kept; ``field`` says which value, for the message."""


def plain(text: str) -> str:
    """Lower case, without accents or umlauts: Restmüll and Restmull match."""
    replaced = text.lower().replace("ß", "ss").replace("ä", "a").replace("ö", "o").replace("ü", "u")
    return unicodedata.normalize("NFKD", replaced).encode("ascii", "ignore").decode("ascii")


def _keys(pattern: str) -> list[str]:
    return [plain(part).strip() for part in re.split(r"[,|]", pattern) if part.strip()]


def type_of(title: str, types: list[dict[str, str]]) -> dict[str, str] | None:
    """The type a title belongs to: the first whose text is in it, else the catch-all."""
    text = plain(title)
    fallback = None
    for kind in types:
        keys = _keys(kind.get("pattern", ""))
        if not keys:
            fallback = fallback or kind
        elif any(key in text for key in keys):
            return kind
    return fallback


def color_of(value: Any) -> str | None:
    """A colour as #RRGGBB, from a hex value or one of Home Assistant's colour names."""
    text = str(value or "").strip()
    if _HEX.fullmatch(text):
        return text.upper()
    return NAMED_COLORS.get(text.lower())


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", plain(text)).strip("-")[:30]


def clean_types(value: Any) -> list[dict[str, str]]:
    """Check a list of types sent by the tablet. Raises WasteTypeError with the reason."""
    if not isinstance(value, list) or not value:
        raise WasteTypeError("types: at least one type")
    if len(value) > MAX_TYPES:
        raise WasteTypeError(f"types: at most {MAX_TYPES}")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise WasteTypeError(f"types[{index}]: not an object")
        label = str(raw.get("label") or "").strip()
        if not label or len(label) > 30:
            raise WasteTypeError(f"types[{index}].label: 1 to 30 characters")
        icon = str(raw.get("icon") or "mdi:trash-can-outline").strip()
        if not _ICON.fullmatch(icon):
            raise WasteTypeError(f"types[{index}].icon: an mdi: icon")
        pattern = str(raw.get("pattern") or "").strip()
        if len(pattern) > 200:
            raise WasteTypeError(f"types[{index}].pattern: at most 200 characters")
        color = color_of(raw.get("color"))
        if color is None:
            raise WasteTypeError(f"types[{index}].color: #RRGGBB")
        kind_id = _slug(str(raw.get("id") or "")) or _slug(label) or f"tipo-{index + 1}"
        while kind_id in seen:
            kind_id = f"{kind_id}-{index + 1}"
        seen.add(kind_id)
        result.append(
            {"id": kind_id, "label": label, "icon": icon, "pattern": pattern, "color": color}
        )
    return result


def types_from_options(options: dict[str, Any]) -> list[dict[str, str]]:
    """The family's types, or the defaults. Colours chosen before 0.6.1 (per kind) still apply."""
    saved = options.get(OPT_WASTE_TYPES)
    if isinstance(saved, list) and saved:
        try:
            return clean_types(saved)
        except WasteTypeError:
            pass
    old_colors = options.get("waste_styles", {})
    return [
        {**kind, "color": color_of(old_colors.get(kind["id"])) or kind["color"]}
        for kind in default_waste_types(str(options.get("language") or "en"))
    ]


def labels_for(titles: list[str], types: list[dict[str, str]]) -> list[str]:
    """The labels for the pickups of a day, each once, in order: ["Organico", "Carta"]."""
    labels: list[str] = []
    for title in titles:
        kind = type_of(title, types)
        label = kind["label"] if kind else title
        if label not in labels:
            labels.append(label)
    return labels
