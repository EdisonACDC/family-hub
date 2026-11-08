"""Readable names for phone and Echo choices in Avvisi."""

from __future__ import annotations

from app.notify import echo_speakers, phone_label, phone_services


def test_phone_service_names_are_readable() -> None:
    assert phone_label("mobile_app_iphone_luca") == "iPhone Luca"
    assert phone_label("mobile_app_ipad_cucina") == "iPad Cucina"
    assert phone_label("mobile_app_sofia") == "Sofia"


def test_phone_services_are_sorted_by_label() -> None:
    result = phone_services({"notify": {"mobile_app_sofia": {}, "mobile_app_iphone_luca": {}}})
    assert [s["label"] for s in result] == ["iPhone Luca", "Sofia"]


def test_echo_uses_the_friendly_name_then_the_registry_name() -> None:
    entries = [
        {"entity_id": "media_player.a", "platform": "alexa_media", "name": None},
        {"entity_id": "media_player.b", "platform": "alexa_media", "name": "Salotto"},
        {"entity_id": "media_player.c", "platform": "other"},
    ]
    states = [{"entity_id": "media_player.a", "attributes": {"friendly_name": "Alexa Cucina"}}]
    result = echo_speakers(entries, states)
    assert result == [
        {"entity_id": "media_player.a", "name": "Alexa Cucina"},
        {"entity_id": "media_player.b", "name": "Salotto"},
    ]
