"""Tests for the multi-agent Discord router."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from chief_of_staff.agent.registry import AgentConfig
from chief_of_staff.agent.router import resolve_agent, get_all_trigger_words


def _make_configs():
    """Create mock agent configs for testing."""
    cos = AgentConfig(
        name="chief_of_staff",
        display_name="Arcuate Chief of Staff",
        discord_name="angie",
        trigger_words=["angie", "agent1", "chief of staff"],
    )
    onboarding = AgentConfig(
        name="onboarding",
        display_name="Onboarding Specialist",
        discord_name="onboarding",
        trigger_words=["onboarding", "new practice", "welcome packet"],
    )
    return [cos, onboarding]


@pytest.fixture
def mock_registry():
    """Mock the agent registry with COS + onboarding agents."""
    configs = _make_configs()
    registry = MagicMock()
    registry.list_agents.return_value = configs
    registry.get.side_effect = lambda name: next((c for c in configs if c.name == name), None)
    with patch("chief_of_staff.agent.router.get_registry", return_value=registry):
        yield registry


class TestResolveAgent:
    """Test agent resolution logic."""

    def test_defaults_to_cos(self, mock_registry):
        """Messages with no matches default to chief_of_staff."""
        assert resolve_agent("how's the weather?") == "chief_of_staff"

    def test_specialist_discord_name(self, mock_registry):
        """Explicit @onboarding mention routes to onboarding agent."""
        assert resolve_agent("hey onboarding, set up the new practice") == "onboarding"

    def test_specialist_trigger_word(self, mock_registry):
        """Trigger word match routes to specialist."""
        assert resolve_agent("we need to prepare a welcome packet for Dr. Kim") == "onboarding"

    def test_cos_discord_name_stays_cos(self, mock_registry):
        """'angie' mention stays with COS (it's the default)."""
        assert resolve_agent("hey angie what's the status?") == "chief_of_staff"

    def test_specialist_trigger_before_cos(self, mock_registry):
        """Specialist trigger words take priority over COS trigger words."""
        # "onboarding" is a specialist trigger word
        assert resolve_agent("can you handle this onboarding task, angie?") == "onboarding"

    def test_dm_defaults_to_cos(self, mock_registry):
        """DMs default to COS when no match."""
        assert resolve_agent("tell me about the pipeline", is_dm=True) == "chief_of_staff"

    def test_new_practice_trigger(self, mock_registry):
        """'new practice' trigger routes to onboarding."""
        assert resolve_agent("we have a new practice signing up tomorrow") == "onboarding"


class TestGetAllTriggerWords:
    """Test merged trigger words collection."""

    def test_merges_all_agents(self, mock_registry):
        """All trigger words and discord names from all agents are merged."""
        words = get_all_trigger_words()
        assert "angie" in words
        assert "onboarding" in words
        assert "welcome packet" in words
        assert "agent1" in words
        assert "chief of staff" in words

    def test_includes_discord_names(self, mock_registry):
        """Discord names are included as trigger words."""
        words = get_all_trigger_words()
        assert "angie" in words
        assert "onboarding" in words
