"""The release asset HACS downloads: hacs.json and the release workflow agree on its name,
and the zip holds the integration's files at its root (HACS unpacks it into
custom_components/<domain>)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from custom_components.family_hub.const import DOMAIN

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / DOMAIN


def test_hacs_downloads_the_release_zip() -> None:
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert hacs["zip_release"] is True
    assert hacs["filename"] == "family_hub.zip"
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "family_hub.zip" in workflow and "cd custom_components/family_hub" in workflow


def test_the_zip_has_the_integration_at_its_root(tmp_path: Path) -> None:
    """The same layout the workflow builds: files of the folder, not the folder itself."""
    target = tmp_path / "family_hub.zip"
    with zipfile.ZipFile(target, "w") as archive:
        for path in INTEGRATION.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(path, path.relative_to(INTEGRATION).as_posix())
    names = set(zipfile.ZipFile(target).namelist())
    needed_files = (
        "manifest.json",
        "__init__.py",
        "guests.py",
        "guest_www/app.js",
        "brand/icon.png",
    )
    for needed in needed_files:
        assert needed in names
    assert not any(name.startswith("custom_components/") for name in names)
