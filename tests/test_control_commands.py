"""Tests for deterministic phone control commands and runtime rails."""

from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import patch

from chief_of_staff.agent.rails import set_llm_enabled
from chief_of_staff.communication.bluebubbles_pairing import (
    get_bluebubbles_pairing_store,
    reset_bluebubbles_pairing_store_for_tests,
)
from chief_of_staff.communication.control_commands import handle_control_message
from chief_of_staff.gateway.exec_approvals import (
    get_exec_approvals_service,
    reset_exec_approvals_service_for_tests,
)
from chief_of_staff.gateway.usage_budget import reset_usage_budget_service_for_tests


def _reset_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "chief_of_staff.gateway.exec_approvals.settings.exec_approvals_path",
        str(tmp_path / "exec-approvals.json"),
    )
    reset_exec_approvals_service_for_tests()
    monkeypatch.setattr(
        "chief_of_staff.communication.bluebubbles_pairing.settings.bluebubbles_pairing_store_path",
        str(tmp_path / "bluebubbles-pairing.json"),
    )
    reset_bluebubbles_pairing_store_for_tests()
    monkeypatch.setattr(
        "chief_of_staff.gateway.usage_budget.settings.usage_ledger_path",
        str(tmp_path / "usage-ledger.json"),
    )
    reset_usage_budget_service_for_tests()
    set_llm_enabled(False)


def test_status_requires_authorized_phone(monkeypatch, tmp_path):
    _reset_state(tmp_path, monkeypatch)
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


def test_status_for_authorized_phone(monkeypatch, tmp_path):
    _reset_state(tmp_path, monkeypatch)
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


def test_cmd_blocked_until_exec_resumed(monkeypatch, tmp_path):
    _reset_state(tmp_path, monkeypatch)
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


def test_cmd_requests_approval_after_resume(monkeypatch, tmp_path):
    _reset_state(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "chief_of_staff.communication.control_commands.settings.command_allowed_phones",
        ["+15550001111"],
    )
    monkeypatch.setattr(
        "chief_of_staff.communication.control_commands.settings.command_allowed_prefixes",
        ["pwd"],
    )
    handle_control_message("+15550001111", "/resume exec")

    result = handle_control_message("+15550001111", "cmd: pwd")
    assert result.handled is True
    assert "Approval required" in result.response

    match = re.search(r"id=([a-f0-9-]+)", result.response)
    assert match
    request_id = match.group(1)
    get_exec_approvals_service().resolve(
        {"requestId": request_id, "decision": "approved", "decidedBy": "owner"}
    )

    completed = SimpleNamespace(returncode=0, stdout="/tmp\n", stderr="")
    with patch(
        "chief_of_staff.communication.control_commands.subprocess.run",
        return_value=completed,
    ) as run_mock:
        second_try = handle_control_message("+15550001111", "cmd: pwd")

    assert run_mock.called
    assert "exit_code=0" in second_try.response


def test_cmd_rejected_if_not_allowlisted(monkeypatch, tmp_path):
    _reset_state(tmp_path, monkeypatch)
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


def test_pair_approve_command(monkeypatch, tmp_path):
    _reset_state(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "chief_of_staff.communication.control_commands.settings.command_allowed_phones",
        ["+15550001111"],
    )
    code = get_bluebubbles_pairing_store().request("+15550009999")
    list_result = handle_control_message("+15550001111", "/pair list")
    assert code in list_result.response

    approve_result = handle_control_message("+15550001111", f"/pair approve {code}")
    assert "Approved BlueBubbles pairing" in approve_result.response
