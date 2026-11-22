"""0.10.6: a yes or no from a calendar event is read as what it says. Home Assistant sends a boolean
as text, so "False" must not become True."""

from __future__ import annotations

from typing import Any

import pytest
from app.server import _flag


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        ("True", True),
        ("False", False),
        ("true", True),
        ("false", False),
        ("1", True),
        ("0", False),
        ("", False),
        (None, False),
    ],
)
def test_a_flag_is_read_as_what_it_says(value: Any, expected: bool) -> None:
    assert _flag(value) is expected
