"""Tests for the AI merge resolver."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest

from chief_of_staff.agent.merge_resolver import (
    ConflictResult,
    analyze_file,
    generate_fix,
    is_high_risk,
    post_to_discord,
    COLOR_BLUE,
    COLOR_GREEN,
    COLOR_RED,
)


class TestIsHighRisk:
    """Test high-risk file detection."""

    def test_agent_yaml(self):
        assert is_high_risk("agents/chief_of_staff.yaml") is True

    def test_tools_py(self):
        assert is_high_risk("src/chief_of_staff/agent/tools.py") is True

    def test_changelog(self):
        assert is_high_risk("architecture_changelog.yaml") is True

    def test_random_file_not_high_risk(self):
        assert is_high_risk("src/chief_of_staff/config.py") is False

    def test_readme_not_high_risk(self):
        assert is_high_risk("README.md") is False


class TestAnalyzeFile:
    """Test AI conflict analysis."""

    @pytest.mark.asyncio
    async def test_no_conflict_detected(self):
        """When Claude says no conflict, result should reflect that."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"text": json.dumps({
                "has_conflict": False,
                "severity": "none",
                "description": "No conflicts detected",
                "suggested_fix": "N/A",
                "auto_fixable": False,
            })}]
        }

        with patch("chief_of_staff.agent.merge_resolver.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                post=AsyncMock(return_value=mock_response)
            ))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await analyze_file(
                "agents/test.yaml", "diff content", "file content", "test-key"
            )

        assert result.has_conflict is False
        assert result.severity == "none"

    @pytest.mark.asyncio
    async def test_conflict_detected(self):
        """When Claude finds a conflict, result should include details."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"text": json.dumps({
                "has_conflict": True,
                "severity": "high",
                "description": "Duplicate tool name 'search_knowledge'",
                "suggested_fix": "Remove the duplicate definition",
                "auto_fixable": True,
            })}]
        }

        with patch("chief_of_staff.agent.merge_resolver.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                post=AsyncMock(return_value=mock_response)
            ))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await analyze_file(
                "src/chief_of_staff/agent/tools.py", "diff", "content", "test-key"
            )

        assert result.has_conflict is True
        assert result.severity == "high"
        assert "Duplicate" in result.description

    @pytest.mark.asyncio
    async def test_api_error_returns_safe_result(self):
        """API errors should return a safe non-conflict result."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("chief_of_staff.agent.merge_resolver.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                post=AsyncMock(return_value=mock_response)
            ))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await analyze_file("test.py", "diff", "content", "test-key")

        assert result.has_conflict is False
        assert "API error" in result.description

    @pytest.mark.asyncio
    async def test_timeout_returns_safe_result(self):
        """Timeouts should return a safe non-conflict result."""
        with patch("chief_of_staff.agent.merge_resolver.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                post=AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            ))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await analyze_file("test.py", "diff", "content", "test-key")

        assert result.has_conflict is False
        assert "timeout" in result.description.lower()


class TestPostToDiscord:
    """Test Discord webhook posting."""

    @pytest.mark.asyncio
    async def test_successful_post(self):
        """Should return True on successful webhook post."""
        mock_response = MagicMock()
        mock_response.status_code = 204

        with patch("chief_of_staff.agent.merge_resolver.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                post=AsyncMock(return_value=mock_response)
            ))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await post_to_discord(
                "https://discord.com/api/webhooks/test",
                "Test Title",
                "Test description",
                COLOR_GREEN,
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_failed_post(self):
        """Should return False on webhook failure."""
        with patch("chief_of_staff.agent.merge_resolver.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                post=AsyncMock(side_effect=httpx.ConnectError("connection refused"))
            ))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await post_to_discord(
                "https://discord.com/api/webhooks/test",
                "Test",
                "desc",
                COLOR_RED,
            )

        assert result is False


class TestConflictResult:
    """Test the ConflictResult dataclass."""

    def test_default_values(self):
        r = ConflictResult(
            file_path="test.py",
            has_conflict=False,
            severity="none",
            description="OK",
            suggested_fix="N/A",
            auto_fixable=False,
        )
        assert r.resolved_content is None
        assert r.file_path == "test.py"
