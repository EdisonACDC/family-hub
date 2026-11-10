"""0.7.8b1: the only donation link in the app is the menu's support entry. No pop-up, banner or
reminder asks for money, and the link is not repeated in the page's files."""

from __future__ import annotations

from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
PAGE_FILES = ["index.html", "app.js", "i18n.js", "app.css"]
MONEY_WORDS = ["donat", "spend", "coffee", "caffè", "buy me", "paypal", "sponsor"]


def _text(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8").lower()


def test_the_ko_fi_link_appears_once_and_only_in_the_menu() -> None:
    assert _text("index.html").count("ko-fi.com/edisonacdc") == 1
    for name in PAGE_FILES:
        if name != "index.html":
            assert "ko-fi" not in _text(name), name


@pytest.mark.parametrize("name", PAGE_FILES)
def test_no_other_request_for_money_in_the_page(name: str) -> None:
    text = _text(name)
    for word in MONEY_WORDS:
        assert word not in text, f"{word!r} in {name}"
