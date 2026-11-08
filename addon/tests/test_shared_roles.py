"""Shared screens: a Home Assistant user that is no person can add and change events, but is
not a guest and does not open the settings."""

from __future__ import annotations

from app.access import (
    ADULT,
    GUEST_IDENTITY,
    SHARED,
    can_change,
    can_see,
    can_write,
    identify,
)

PERSONS = [{"id": "mamma", "ha_user_id": "u-mamma", "role": "adult"}]


def test_a_shared_user_is_a_shared_screen_not_a_guest() -> None:
    identity = identify("u-cucina", PERSONS, ["u-cucina"])
    assert identity.role == SHARED
    assert identity.person_id is None


def test_a_user_that_is_neither_linked_nor_shared_stays_a_guest() -> None:
    assert identify("u-altro", PERSONS, ["u-cucina"]) == GUEST_IDENTITY


def test_a_shared_screen_adds_changes_and_sees_everything() -> None:
    identity = identify("u-cucina", PERSONS, ["u-cucina"])
    assert can_write(identity)
    assert can_see(identity, ["sofia"])
    assert can_change(identity, ["sofia"])


def test_a_guest_still_changes_nothing() -> None:
    assert not can_write(GUEST_IDENTITY)
    assert not can_change(GUEST_IDENTITY, ["sofia"])


def test_a_linked_person_keeps_their_own_role() -> None:
    identity = identify("u-mamma", PERSONS, ["u-mamma"])
    assert identity.role == ADULT
    assert identity.person_id == "mamma"
