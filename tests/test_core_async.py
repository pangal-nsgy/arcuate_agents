"""Tests for core.py — verify AsyncAnthropic client is used.

Requires full dependency stack (chromadb, etc). Skip if not available.
"""

import pytest

try:
    from chief_of_staff.agent.core import Agent
    from chief_of_staff.agent.registry import AgentConfig
    import anthropic
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


@pytest.mark.skipif(not HAS_DEPS, reason="Full dependency stack not installed")
class TestAsyncClient:
    """Verify the agent uses AsyncAnthropic, not sync Anthropic."""

    def test_client_is_async(self):
        config = AgentConfig(
            name="test_agent",
            display_name="Test",
            system_prompt="test",
            tools=[],
        )
        agent = Agent(config)
        assert isinstance(agent.client, anthropic.AsyncAnthropic)
