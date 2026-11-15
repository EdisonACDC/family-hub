"""README badges: only stable releases and stable versions are counted."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "badge_stats", ROOT / ".github" / "scripts" / "badge_stats.py"
)
assert _SPEC and _SPEC.loader
stats = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(stats)


def test_only_stable_versions_count() -> None:
    for version in ("0.9.0", "1.10.2", "v1.0", "2"):
        assert stats.is_stable(version), version
    for version in (
        "0.9.0b9",
        "0.9.0rc1",
        "0.9.0.dev3",
        "1.0.0+local1",
        "2.0.6-dev-45e95e9",
        "1.0a1",
    ):
        assert not stats.is_stable(version), version


def test_downloads_skip_pre_releases_and_drafts() -> None:
    releases = [
        {"tag_name": "v0.9.0", "prerelease": False, "assets": [{"download_count": 12}]},
        {"tag_name": "v0.9.0b9", "prerelease": True, "assets": [{"download_count": 40}]},
        {
            "tag_name": "v0.9.1",
            "prerelease": False,
            "draft": True,
            "assets": [{"download_count": 3}],
        },
        {"tag_name": "v0.8.0", "prerelease": False, "assets": []},
        {"tag_name": "v1.0.0", "prerelease": False, "assets": [{"download_count": 5}, {}]},
    ]
    assert stats.stable_downloads(releases) == 17


def test_installs_sum_stable_versions_only() -> None:
    analytics = {
        "family_hub": {
            "total": 30,
            "versions": {"0.9.0": 10, "0.8.0": 5, "0.9.0b9": 14, "0.9.1rc1": 1},
        },
        "other": {"total": 99, "versions": {"1.0.0": 99}},
    }
    assert stats.stable_installs(analytics) == 15
    assert stats.stable_installs({}) == 0
    assert stats.badge(15) == {"schemaVersion": 1, "label": "", "message": "15", "color": "blue"}
