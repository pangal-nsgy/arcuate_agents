"""Tests for the core agent loop."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chief_of_staff.agent.core import Agent
from chief_of_staff.agent.registry import AgentConfig


@pytest.fixture
def agent(agent_config, mock_anthropic_client):
    """An Agent instance with a mocked Anthropic client."""
    a = Agent(agent_config)
    a.client = mock_anthropic_client
    return a


@pytest.mark.asyncio
async def test_respond_returns_text(agent, mock_anthropic_response):
    """Normal agent response returns the text content."""
    agent.client.messages.create = AsyncMock(
        return_value=mock_anthropic_response("Here is my answer.")
    )
    with patch("chief_of_staff.agent.core.get_registry") as mock_reg:
        mock_reg.return_value.get.return_value = agent.config
        with patch("chief_of_staff.knowledge.store.get_context_for_query", return_value=""):
            result = await agent.respond("What is Arcuate?")
    assert "Here is my answer." in result


@pytest.mark.asyncio
async def test_respond_timeout(agent_config):
    """Request exceeding timeout returns a friendly timeout message."""
    agent_config.request_timeout = 1  # 1 second timeout

    agent = Agent(agent_config)

    # Make the API call hang forever
    async def slow_create(**kwargs):
        await asyncio.sleep(100)

    agent.client = MagicMock()
    agent.client.messages.create = slow_create

    with patch("chief_of_staff.agent.core.get_registry") as mock_reg:
        mock_reg.return_value.get.return_value = agent_config
        with patch("chief_of_staff.knowledge.store.get_context_for_query", return_value=""):
            result = await agent.respond("Tell me everything")

    assert "too long" in result.lower()


@pytest.mark.asyncio
async def test_respond_iteration_limit(agent, mock_anthropic_response):
    """Hitting max_iterations returns a limit message."""
    agent.config.max_iterations = 2

    # Always return tool calls so the loop never terminates naturally
    tool_response = mock_anthropic_response(
        tool_calls=[{"name": "search_knowledge", "input": {"query": "test"}, "id": "t1"}]
    )
    agent.client.messages.create = AsyncMock(return_value=tool_response)

    with patch("chief_of_staff.agent.core.get_registry") as mock_reg:
        mock_reg.return_value.get.return_value = agent.config
        with patch("chief_of_staff.knowledge.store.get_context_for_query", return_value=""):
            with patch("chief_of_staff.agent.core.execute_tool", new_callable=AsyncMock, return_value="result"):
                result = await agent.respond("Do a lot of things")

    assert "limit" in result.lower() or "breaking down" in result.lower()
