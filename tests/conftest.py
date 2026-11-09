"""Shared test fixtures."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> Generator[None]:
    """Let Home Assistant load custom_components/family_hub in every test."""
    yield


@pytest.fixture(autouse=True)
def no_real_waiting_for_echos(monkeypatch: pytest.MonkeyPatch) -> None:
    """An announcement at a chosen volume waits for the Echos to change it, at least a couple of
    seconds. Tests do not wait: the wait is checked where it is tested."""
    monkeypatch.setattr("custom_components.family_hub.notifier.ECHO_WAIT_MIN_SECONDS", 0)
