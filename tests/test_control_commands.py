"""Tests for deterministic phone control commands and runtime rails."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from chief_of_staff.agent.rails import set_command_exec_enabled, set_llm_enabled
from chief_of_staff.communication.control_commands import handle_control_message


def _reset_rails() -> None:
    set_llm_enabled(False)
    set_command_exec_enabled(False)


def test_status_requires_authorized_phone(monkeypatch):
    _reset_rails()
    monkeypatch.setattr(
        "chief_of_staff.communication.control_commands.settings.command_allowed_phones",
        ["+15550001111"],
    )
    monkeypatch.setattr(
        "chief_of_staff.communication.control_commands.settings.founder_phone_numbers",
        [],
    )
    result = handle_control_message("+15550002222", "/status")
    assert result.handled is True
    assert "Unauthorized number" in result.response


def test_status_for_authorized_phone(monkeypatch):
    _reset_rails()
    monkeypatch.setattr(
        "chief_of_staff.communication.control_commands.settings.command_allowed_phones",
        ["+15550001111"],
    )
    monkeypatch.setattr(
        "chief_of_staff.communication.control_commands.settings.command_allowed_prefixes",
        ["pwd"],
    )
    result = handle_control_message("+15550001111", "/status")
    assert result.handled is True
    assert "llm_enabled=False" in result.response
    assert "command_exec_enabled=False" in result.response


def test_cmd_blocked_until_exec_resumed(monkeypatch):
    _reset_rails()
    monkeypatch.setattr(
        "chief_of_staff.communication.control_commands.settings.command_allowed_phones",
        ["+15550001111"],
    )
    monkeypatch.setattr(
        "chief_of_staff.communication.control_commands.settings.command_allowed_prefixes",
        ["pwd"],
    )
    result = handle_control_message("+15550001111", "cmd: pwd")
    assert result.handled is True
    assert "paused" in result.response.lower()


def test_cmd_runs_after_resume(monkeypatch):
    _reset_rails()
    monkeypatch.setattr(
        "chief_of_staff.communication.control_commands.settings.command_allowed_phones",
        ["+15550001111"],
    )
    monkeypatch.setattr(
        "chief_of_staff.communication.control_commands.settings.command_allowed_prefixes",
        ["pwd"],
    )
    handle_control_message("+15550001111", "/resume exec")

    completed = SimpleNamespace(returncode=0, stdout="/tmp\n", stderr="")
    with patch(
        "chief_of_staff.communication.control_commands.subprocess.run",
        return_value=completed,
    ) as run_mock:
        result = handle_control_message("+15550001111", "cmd: pwd")

    assert run_mock.called
    assert "exit_code=0" in result.response


def test_cmd_rejected_if_not_allowlisted(monkeypatch):
    _reset_rails()
    monkeypatch.setattr(
        "chief_of_staff.communication.control_commands.settings.command_allowed_phones",
        ["+15550001111"],
    )
    monkeypatch.setattr(
        "chief_of_staff.communication.control_commands.settings.command_allowed_prefixes",
        ["pwd"],
    )
    handle_control_message("+15550001111", "/resume exec")
    result = handle_control_message("+15550001111", "cmd: rm -rf /")
    assert result.handled is True
    assert "blocked by allowlist" in result.response.lower()
