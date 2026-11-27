"""The brand images of the integration (0.11.1). hassfest, run by the HACS checks, refuses a dark
image that is identical to its normal one ("[BRAND_IMAGES] ... is identical to ..."). The folder
keeps only the icon and the logo (with @2x), and a dark variant of each only when it differs."""

from __future__ import annotations

import hashlib
from pathlib import Path

import custom_components.family_hub  # noqa: F401  (the integration is on the path for the tests)

BRAND = Path(__file__).resolve().parents[1] / "custom_components" / "family_hub" / "brand"

# The names hassfest and HACS know for a custom integration.
ALLOWED = {
    "icon.png",
    "icon@2x.png",
    "logo.png",
    "logo@2x.png",
    "dark_icon.png",
    "dark_icon@2x.png",
    "dark_logo.png",
    "dark_logo@2x.png",
}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files() -> list[Path]:
    return sorted(path for path in BRAND.iterdir() if path.is_file())


def test_the_brand_folder_has_the_icon_and_the_logo() -> None:
    names = {path.name for path in _files()}
    assert {"icon.png", "icon@2x.png", "logo.png", "logo@2x.png"} <= names


def test_there_are_no_stray_brand_files() -> None:
    stray = [path.name for path in _files() if path.name not in ALLOWED]
    assert not stray, f"brand files hassfest does not expect: {stray}"


def test_a_dark_image_is_never_identical_to_its_normal_one() -> None:
    for dark in _files():
        if not dark.name.startswith("dark_"):
            continue
        normal = BRAND / dark.name.removeprefix("dark_")
        if not normal.exists():
            continue
        assert _digest(dark) != _digest(normal), (
            f"{dark.name} is identical to {normal.name}: remove it"
        )
