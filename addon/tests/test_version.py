"""Versions: a beta is written 0.7.7b1 for Home Assistant and v0.7.7-beta.1 for its tag; both
spellings are the same version when the add-on and the integration are compared."""

from __future__ import annotations

import pytest
from app.version import ADDON_VERSION, same_version


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("0.7.7b1", "0.7.7-beta.1"),
        ("0.7.7b2", "v0.7.7-beta.2"),
        ("0.7.7b1", "0.7.7b1"),
        ("0.7.7", "v0.7.7"),
    ],
)
def test_the_same_version_in_two_spellings_is_the_same(first: str, second: str) -> None:
    assert same_version(first, second)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("0.7.7b1", "0.7.7b2"),
        ("0.7.7b1", "0.7.7"),
        ("0.7.6", "0.7.7b1"),
        ("0.7.7b1", ""),
    ],
)
def test_different_versions_are_different(first: str, second: str) -> None:
    assert not same_version(first, second)


def test_the_add_on_version_is_a_beta_with_the_expected_tag() -> None:
    assert ADDON_VERSION == "0.7.8"
    assert same_version(ADDON_VERSION, "v0.7.8")
