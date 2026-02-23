"""Tests for transcript-driven voice command parsing."""

from __future__ import annotations

from chief_of_staff.ingestion.voice_commands import extract_voice_command


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

