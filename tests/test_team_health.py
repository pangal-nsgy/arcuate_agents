"""Tests for team health monitoring — pulse, engagement, catch-up."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chief_of_staff.agent.team_health import (
    generate_weekly_pulse,
    check_engagement_alerts,
    generate_catchup,
)


class TestWeeklyPulse:
    """Weekly pulse generation tests."""

    @pytest.mark.asyncio
    async def test_calls_agent_respond(self):
        """Pulse calls agent.respond() with activity data."""
        mock_agent = MagicMock()
        mock_agent.respond = AsyncMock(return_value="**Weekly Pulse**\n- Team is active")

        mock_config = MagicMock()
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_config

        with patch("chief_of_staff.agent.registry.get_registry", return_value=mock_registry), \
             patch("chief_of_staff.agent.core.Agent", return_value=mock_agent), \
             patch("chief_of_staff.agent.activity.get_recent_activity", return_value=[]), \
             patch("chief_of_staff.config.settings") as mock_settings:
            mock_settings.founder_emails = []
            result = await generate_weekly_pulse()

        assert "Weekly Pulse" in result
        mock_agent.respond.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_empty_on_missing_config(self):
        """Returns empty string if agent config not found."""
        mock_registry = MagicMock()
        mock_registry.get.return_value = None

        with patch("chief_of_staff.agent.registry.get_registry", return_value=mock_registry), \
             patch("chief_of_staff.agent.activity.get_recent_activity", return_value=[]), \
             patch("chief_of_staff.config.settings") as mock_settings:
            mock_settings.founder_emails = []
            result = await generate_weekly_pulse()

        assert result == ""


class TestEngagementAlerts:
    """Engagement monitoring tests."""

    @pytest.mark.asyncio
    async def test_no_alerts_when_no_founders_configured(self):
        """Returns empty list if no founder emails configured."""
        with patch("chief_of_staff.config.settings") as mock_settings:
            mock_settings.founder_emails = []
            alerts = await check_engagement_alerts()

        assert alerts == []

    @pytest.mark.asyncio
    async def test_alerts_when_founder_inactive(self):
        """Returns alert when a founder has no recent activity."""
        with patch("chief_of_staff.config.settings") as mock_settings, \
             patch("chief_of_staff.agent.activity.get_recent_activity", return_value=[]):
            mock_settings.founder_emails = ["inactive@example.com"]
            alerts = await check_engagement_alerts()

        assert len(alerts) >= 1
        assert "inactive@example.com" in alerts[0]


class TestCatchup:
    """Catch-up summary tests."""

    @pytest.mark.asyncio
    async def test_generates_catchup(self):
        """Generates catch-up summary for a team member."""
        mock_agent = MagicMock()
        mock_agent.respond = AsyncMock(return_value="**Catch-up for Dan**\n- 3 new emails")

        mock_config = MagicMock()
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_config

        with patch("chief_of_staff.agent.registry.get_registry", return_value=mock_registry), \
             patch("chief_of_staff.agent.core.Agent", return_value=mock_agent), \
             patch("chief_of_staff.agent.activity.log_activity"):
            result = await generate_catchup("Dan", days=3)

        assert "Catch-up" in result
        mock_agent.respond.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self):
        """Returns empty string on agent error."""
        mock_agent = MagicMock()
        mock_agent.respond = AsyncMock(side_effect=Exception("timeout"))
        mock_config = MagicMock()
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_config

        with patch("chief_of_staff.agent.registry.get_registry", return_value=mock_registry), \
             patch("chief_of_staff.agent.core.Agent", return_value=mock_agent):
            result = await generate_catchup("Dan")

        assert result == ""
