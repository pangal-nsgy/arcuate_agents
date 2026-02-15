"""Shared test fixtures for the Chief of Staff agent tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from chief_of_staff.agent.registry import AgentConfig


@pytest.fixture
def agent_config() -> AgentConfig:
    """A minimal agent config for testing."""
    return AgentConfig(
        name="test_agent",
        display_name="Test Agent",
        model="claude-sonnet-4-5-20250929",
        max_tokens=1024,
        max_iterations=5,
        system_prompt="You are a test agent.",
        tools=["search_knowledge"],
        request_timeout=10,
    )


@pytest.fixture
def mock_anthropic_response():
    """Factory for mock Anthropic API responses."""
    def _make(text: str = "Hello!", tool_calls: list[dict] | None = None):
        if tool_calls:
            content = []
            for tc in tool_calls:
                block = MagicMock()
                block.type = "tool_use"
                block.name = tc["name"]
                block.input = tc.get("input", {})
                block.id = tc.get("id", "tool_123")
                content.append(block)
            response = MagicMock()
            response.content = content
            return response
        else:
            text_block = MagicMock()
            text_block.type = "text"
            text_block.text = text
            response = MagicMock()
            response.content = [text_block]
            return response
    return _make


@pytest.fixture
def mock_anthropic_client(mock_anthropic_response):
    """A mock AsyncAnthropic client that returns text responses by default."""
    client = AsyncMock()
    client.messages.create = AsyncMock(return_value=mock_anthropic_response("Hello from the agent!"))
    return client
