"""On a beta, the repository and the app say "(beta)" in the store, so they are not mistaken for
the stable ones; on a stable version they must not. The version decides, so the names can never
reach a stable release by mistake."""

from __future__ import annotations

import re
from pathlib import Path

from app.version import ADDON_VERSION

ROOT = Path(__file__).resolve().parents[2]


def _name(path: Path) -> str:
    match = re.search(r"^name:\s*(.+)$", path.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, path
    return match.group(1).strip().strip('"')


def test_names_follow_the_version() -> None:
    beta = bool(re.search(r"(?:b|beta)\d+$", ADDON_VERSION))
    repository = _name(ROOT / "repository.yaml")
    app = _name(ROOT / "addon" / "config.yaml")
    if beta:
        assert repository == "Family Hub (beta)"
        assert app == "Family Hub UI (beta)"
    else:
        assert repository == "Family Hub"
        assert app == "Family Hub UI"
