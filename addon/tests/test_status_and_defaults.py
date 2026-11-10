"""0.7.6 (rule C): the add-on says what is missing or out of date, and its default rubbish types
follow the family's language. The add-on version is the one in config.yaml."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.version import ADDON_VERSION
from app.waste import default_waste_types, waste_kind

from tests.fake_ha import FakeHA
from tests.helpers import ADULT_USER, connect, request, shutdown, started

CONFIG = Path(__file__).resolve().parents[1] / "config.yaml"


def _status(fake: FakeHA) -> Any:
    async def scenario() -> Any:
        ha_server, client, _ = await started(fake)
        try:
            ws = await connect(client, ADULT_USER)
            reply = await request(ws, {"id": 1, "op": "status"})
            await ws.close()
            return reply["result"]
        finally:
            await shutdown(ha_server, client)

    return asyncio.run(scenario())


def test_the_add_on_version_is_the_one_in_config_yaml() -> None:
    text = CONFIG.read_text(encoding="utf-8")
    line = next(part for part in text.splitlines() if part.startswith("version:"))
    assert line.split('"')[1] == ADDON_VERSION


def test_all_well_when_the_versions_agree() -> None:
    result = _status(FakeHA())
    assert result == {"addon": ADDON_VERSION, "integration": ADDON_VERSION, "problem": None}


def test_a_different_integration_version_is_said_clearly() -> None:
    fake = FakeHA()
    fake.integration_version = "0.7.4"
    result = _status(fake)
    assert result["problem"] == "version"
    assert result["integration"] == "0.7.4"
    assert result["addon"] == ADDON_VERSION


def test_a_missing_integration_is_said_clearly() -> None:
    fake = FakeHA()
    fake.integration_installed = False
    result = _status(fake)
    assert result["problem"] == "not_installed"
    assert result["integration"] is None


def test_an_integration_without_a_family_says_to_finish_the_setup() -> None:
    fake = FakeHA()
    fake.configured = False
    assert _status(fake)["problem"] == "not_configured"


def test_default_rubbish_types_follow_the_language() -> None:
    cases = {
        "it": {"Organico": "bio", "Plastica": "gelb", "Carta": "papier", "Vetro": "glas"},
        "de": {"Biomüll": "bio", "Gelbe Tonne": "gelb", "Papier": "papier", "Glas": "glas"},
        "en": {"Food waste": "bio", "Recycling": "gelb", "Paper": "papier", "Glass": "glas"},
    }
    for language, titles in cases.items():
        types = default_waste_types(language)
        assert [t["id"] for t in types] == ["restmuell", "bio", "gelb", "papier", "glas", "altro"]
        for title, kind in titles.items():
            assert waste_kind(title, language) == kind, (language, title)
        assert waste_kind("Nothing like it", language) == "altro"
        assert all(t["label"] for t in types)


def test_unknown_language_falls_back_to_english() -> None:
    assert default_waste_types("fr") == default_waste_types("en")
