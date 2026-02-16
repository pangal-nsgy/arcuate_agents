"""Tests for briefing generators — daily briefing, meeting debrief."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chief_of_staff.agent.briefing import (
    generate_daily_briefing,
    generate_meeting_debrief,
    _extract_tldr,
)


class TestDailyBriefing:
    """Daily briefing generation tests."""

    @pytest.mark.asyncio
    async def test_calls_agent_respond(self):
        """Briefing calls agent.respond() with structured prompt."""
        mock_agent = MagicMock()
        mock_agent.respond = AsyncMock(return_value="**Morning Briefing**\n- 5 new emails")

        mock_config = MagicMock()
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_config

        with patch("chief_of_staff.agent.registry.get_registry", return_value=mock_registry), \
             patch("chief_of_staff.agent.core.Agent", return_value=mock_agent):
            result = await generate_daily_briefing()

        assert "Morning Briefing" in result
        mock_agent.respond.assert_called_once()
        call_kwargs = mock_agent.respond.call_args
        assert "briefing" in call_kwargs.kwargs.get("user_message", call_kwargs.args[0] if call_kwargs.args else "").lower() or \
               call_kwargs.kwargs.get("channel") == "scheduler"

    @pytest.mark.asyncio
    async def test_returns_empty_on_missing_config(self):
        """Returns empty string if agent config not found."""
        mock_registry = MagicMock()
        mock_registry.get.return_value = None

        with patch("chief_of_staff.agent.registry.get_registry", return_value=mock_registry):
            result = await generate_daily_briefing()

        assert result == ""

    @pytest.mark.asyncio
    async def test_returns_empty_on_agent_error(self):
        """Returns empty string if agent.respond() raises."""
        mock_agent = MagicMock()
        mock_agent.respond = AsyncMock(side_effect=Exception("API error"))

        mock_config = MagicMock()
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_config

        with patch("chief_of_staff.agent.registry.get_registry", return_value=mock_registry), \
             patch("chief_of_staff.agent.core.Agent", return_value=mock_agent):
            result = await generate_daily_briefing()

        assert result == ""


class TestMeetingDebrief:
    """Meeting debrief generation tests."""

    @pytest.mark.asyncio
    async def test_parses_important_yes(self):
        """Detects IMPORTANT: YES flag in agent response."""
        mock_agent = MagicMock()
        mock_agent.respond = AsyncMock(
            return_value="**TL;DR** Great meeting.\n\nIMPORTANT: YES"
        )
        mock_config = MagicMock()
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_config

        with patch("chief_of_staff.agent.registry.get_registry", return_value=mock_registry), \
             patch("chief_of_staff.agent.core.Agent", return_value=mock_agent):
            feedback, is_important = await generate_meeting_debrief("Team Sync", "transcript text")

        assert is_important is True
        assert "Great meeting" in feedback

    @pytest.mark.asyncio
    async def test_parses_important_no(self):
        """Detects IMPORTANT: NO flag in agent response."""
        mock_agent = MagicMock()
        mock_agent.respond = AsyncMock(
            return_value="**TL;DR** Routine check-in.\n\nIMPORTANT: NO"
        )
        mock_config = MagicMock()
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_config

        with patch("chief_of_staff.agent.registry.get_registry", return_value=mock_registry), \
             patch("chief_of_staff.agent.core.Agent", return_value=mock_agent):
            feedback, is_important = await generate_meeting_debrief("Standup", "transcript")

        assert is_important is False

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self):
        """Returns empty on agent error."""
        mock_agent = MagicMock()
        mock_agent.respond = AsyncMock(side_effect=Exception("timeout"))
        mock_config = MagicMock()
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_config

        with patch("chief_of_staff.agent.registry.get_registry", return_value=mock_registry), \
             patch("chief_of_staff.agent.core.Agent", return_value=mock_agent):
            feedback, is_important = await generate_meeting_debrief("Test", "transcript")

        assert feedback == ""
        assert is_important is False


class TestExtractTldr:
    """TL;DR extraction from meeting feedback."""

    def test_extracts_tldr_section(self):
        """Extracts TL;DR content from formatted feedback."""
        feedback = "**TL;DR** This was a productive meeting about pricing.\n\n**Key Decisions**\n- New pricing..."
        result = _extract_tldr(feedback)
        assert "productive meeting" in result

    def test_fallback_to_first_paragraph(self):
        """Falls back to first paragraph if no TL;DR header found."""
        feedback = "This meeting covered onboarding updates.\n\nSecond paragraph here."
        result = _extract_tldr(feedback)
        assert "onboarding updates" in result

    def test_handles_empty_string(self):
        """Handles empty feedback gracefully."""
        result = _extract_tldr("")
        assert result == ""
