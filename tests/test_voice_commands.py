"""Tests for transcript-driven voice command parsing."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from chief_of_staff.ingestion.voice_commands import extract_voice_command
from chief_of_staff.ingestion.voice_commands import handle_transcript_command
from chief_of_staff.gateway.exec_approvals import (
    get_exec_approvals_service,
    reset_exec_approvals_service_for_tests,
)


def test_extract_voice_command_with_default_prefix(monkeypatch):
    monkeypatch.setattr(
        "chief_of_staff.ingestion.voice_commands.settings.voice_command_prefixes",
        ["agent execute", "execute task"],
    )
    assert extract_voice_command("agent execute summarize this call") == "summarize this call"


def test_extract_voice_command_case_insensitive_prefix(monkeypatch):
    monkeypatch.setattr(
        "chief_of_staff.ingestion.voice_commands.settings.voice_command_prefixes",
        ["agent execute"],
    )
    assert extract_voice_command("Agent Execute make me a checklist") == "make me a checklist"


def test_extract_voice_command_returns_empty_without_prefix(monkeypatch):
    monkeypatch.setattr(
        "chief_of_staff.ingestion.voice_commands.settings.voice_command_prefixes",
        ["agent execute"],
    )
    assert extract_voice_command("please summarize") == ""


@pytest.mark.asyncio
async def test_handle_transcript_command_dry_run_returns_approval_id(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "chief_of_staff.gateway.exec_approvals.settings.exec_approvals_path",
        str(tmp_path / "exec-approvals.json"),
    )
    reset_exec_approvals_service_for_tests()
    monkeypatch.setattr("chief_of_staff.ingestion.voice_commands.settings.voice_exec_enabled", True)
    monkeypatch.setattr("chief_of_staff.ingestion.voice_commands.settings.voice_exec_dry_run", True)
    monkeypatch.setattr("chief_of_staff.ingestion.voice_commands.settings.voice_command_prefixes", ["agent execute"])

    out = await handle_transcript_command("bot1", "Ada", "agent execute summarize this")
    assert "[dry-run]" in out
    assert "id=" in out


@pytest.mark.asyncio
async def test_handle_transcript_command_pending_without_resolution(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "chief_of_staff.gateway.exec_approvals.settings.exec_approvals_path",
        str(tmp_path / "exec-approvals.json"),
    )
    reset_exec_approvals_service_for_tests()
    monkeypatch.setattr("chief_of_staff.ingestion.voice_commands.settings.voice_exec_enabled", True)
    monkeypatch.setattr("chief_of_staff.ingestion.voice_commands.settings.voice_exec_dry_run", False)
    monkeypatch.setattr("chief_of_staff.ingestion.voice_commands.settings.voice_command_prefixes", ["agent execute"])
    monkeypatch.setattr("chief_of_staff.ingestion.voice_commands.settings.voice_approval_wait_ms", 1)

    out = await handle_transcript_command("bot1", "Ada", "agent execute summarize this")
    assert "Approval required" in out


@pytest.mark.asyncio
async def test_handle_transcript_command_executes_when_preapproved(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "chief_of_staff.gateway.exec_approvals.settings.exec_approvals_path",
        str(tmp_path / "exec-approvals.json"),
    )
    reset_exec_approvals_service_for_tests()
    monkeypatch.setattr("chief_of_staff.ingestion.voice_commands.settings.voice_exec_enabled", True)
    monkeypatch.setattr("chief_of_staff.ingestion.voice_commands.settings.voice_exec_dry_run", False)
    monkeypatch.setattr("chief_of_staff.ingestion.voice_commands.settings.voice_command_prefixes", ["agent execute"])
    monkeypatch.setattr("chief_of_staff.ingestion.voice_commands.settings.voice_approval_wait_ms", 1)

    approvals = get_exec_approvals_service()
    original_request = approvals.request_approval

    def _request_and_auto_approve(payload):
        record = original_request(payload)
        approvals.resolve(
            {"requestId": record["requestId"], "decision": "approved", "decidedBy": "operator"}
        )
        return record

    monkeypatch.setattr("chief_of_staff.ingestion.voice_commands.get_agent", lambda: type("A", (), {"respond": AsyncMock(return_value="ok")})())
    monkeypatch.setattr(
        "chief_of_staff.ingestion.voice_commands.get_exec_approvals_service",
        lambda: approvals,
    )
    monkeypatch.setattr(approvals, "request_approval", _request_and_auto_approve)

    out = await handle_transcript_command("bot1", "Ada", "agent execute summarize this")
    assert "Voice command executed" in out
