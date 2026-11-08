"""Shared screens are Home Assistant users that are no person. A linked user is never one."""

from __future__ import annotations

import pytest

from custom_components.family_hub.api import ConfigError, clean_shared_users

PERSONS = [{"id": "mamma", "ha_user_id": "u-mamma"}]


def test_linked_users_are_not_shared_screens() -> None:
    assert clean_shared_users(["u-mamma", "u-cucina", "u-cucina"], PERSONS) == ["u-cucina"]


def test_only_a_list_of_user_ids_is_accepted() -> None:
    with pytest.raises(ConfigError):
        clean_shared_users("u-cucina", PERSONS)
    with pytest.raises(ConfigError):
        clean_shared_users([""], PERSONS)
