"""The add-on's icon and logo are real pictures of the sizes Home Assistant shows. (The older files
were 325 bytes and did not open, so Home Assistant showed a blank icon.)"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

ADDON = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(("name", "size"), [("icon.png", (128, 128)), ("logo.png", (250, 100))])
def test_the_add_on_picture_opens_and_has_its_size(name: str, size: tuple[int, int]) -> None:
    path = ADDON / name
    assert path.stat().st_size > 1000, f"{name} is too small to be a picture"
    with Image.open(path) as image:
        image.load()
        assert image.size == size
        # Not empty: some pixel is visible.
        assert image.convert("RGBA").getextrema()[3][1] > 0, f"{name} is fully transparent"


def test_the_logo_text_is_not_cut_at_the_right_edge() -> None:
    """The last three columns of the logo hold no picture: a longer word would run off the edge."""
    with Image.open(ADDON / "logo.png") as image:
        rgba = image.convert("RGBA")
        width, height = rgba.size
        for x in range(width - 3, width):
            column_alpha = [rgba.getpixel((x, y))[3] for y in range(height)]
            assert max(column_alpha) == 0, f"column {x} has visible pixels"
