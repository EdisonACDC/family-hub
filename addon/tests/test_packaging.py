"""The add-on starts the way Home Assistant add-ons must: through s6 services, so the
Supervisor's environment (SUPERVISOR_TOKEN) reaches the program, and a failure stops the add-on."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from app import server

ADDON = Path(__file__).resolve().parents[1]
SERVICE = ADDON / "rootfs" / "etc" / "services.d" / "family_hub"


def test_dockerfile_has_no_direct_command_and_installs_the_service() -> None:
    lines = [
        line.strip() for line in (ADDON / "Dockerfile").read_text(encoding="utf-8").splitlines()
    ]
    assert not [line for line in lines if line.startswith("CMD")]
    assert "COPY rootfs /" in lines
    chmod = [line for line in lines if line.startswith("RUN chmod")]
    assert (
        chmod
        and "services.d/family_hub/run" in chmod[0]
        and "services.d/family_hub/finish" in chmod[0]
    )


def test_run_starts_the_program_with_the_add_on_environment() -> None:
    text = (SERVICE / "run").read_bytes()
    assert text.startswith(b"#!/usr/bin/with-contenv bashio\n")
    assert b"\r" not in text
    assert b"exec python3 -m app.server" in text


def test_finish_stops_the_container_when_the_service_fails() -> None:
    text = (SERVICE / "finish").read_bytes()
    assert text.startswith(b"#!/usr/bin/execlineb -S0\n")
    assert b"\r" not in text
    assert b"/run/s6/basedir/bin/halt" in text
    assert b"s6-test ${1} -ne 0" in text


def test_scripts_keep_unix_line_endings_in_git() -> None:
    rules = (ADDON.parent / ".gitattributes").read_text(encoding="utf-8")
    assert "services.d/**/run text eol=lf" in rules
    assert "services.d/**/finish text eol=lf" in rules


def test_missing_token_logs_variable_names_never_values(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.delenv("HA_TOKEN", raising=False)
    monkeypatch.setenv("SUPERVISOR_EXAMPLE_NAME", "valore-segreto-da-non-stampare")
    caplog.set_level(logging.ERROR, logger="app.server")
    with pytest.raises(SystemExit):
        server.main()
    assert "SUPERVISOR_EXAMPLE_NAME" in caplog.text
    assert "valore-segreto-da-non-stampare" not in caplog.text
