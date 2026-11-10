"""The add-on's version. It must equal the one in config.yaml (a test checks it).

Versions are written as Home Assistant and Supervisor read them (0.7.7b1 for a beta), while a
GitHub tag is written v0.7.7-beta.1. ``same_version`` treats both spellings as one version, so the
add-on and the integration are compared fairly.
"""

from __future__ import annotations

import re

ADDON_VERSION = "0.7.8b1"

_BETA = re.compile(r"^(\d+\.\d+\.\d+)(?:[-.]?(?:beta|b)[-.]?(\d+))?$")


def _normal(version: str) -> str:
    """0.7.7-beta.1, v0.7.7-beta.1 and 0.7.7b1 all become 0.7.7b1; a release stays as it is."""
    text = version.strip().lower().removeprefix("v")
    match = _BETA.match(text)
    if match is None:
        return text
    core, number = match.group(1), match.group(2)
    return f"{core}b{number}" if number else core


def same_version(first: str, second: str) -> bool:
    """True when two version strings name the same version, whatever their spelling."""
    return _normal(first) == _normal(second)
