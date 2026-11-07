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
