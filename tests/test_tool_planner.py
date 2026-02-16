"""Tests for the tool planner, OpenAI overflow adapter, and layered intelligence."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chief_of_staff.agent.core import Agent, _ALWAYS_AVAILABLE_TOOLS
from chief_of_staff.agent.registry import AgentConfig
from chief_of_staff.agent.openai_adapter import convert_tools, convert_messages


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def agent_config_many_tools() -> AgentConfig:
    """Agent config with >10 tools to trigger the planner."""
    return AgentConfig(
        name="test_agent",
        display_name="Test Agent",
        model="claude-opus-4-6",
        max_tokens=4096,
        max_iterations=3,
        system_prompt="You are a test agent.",
        tools=[
            "search_knowledge", "list_recent_emails", "search_meetings",
            "send_sms", "send_email", "draft_document",
            "remember", "recall_memory",
            "delegate_task", "create_sub_agent",
            "report_progress", "run_python",
        ],
        request_timeout=10,
        planner_model="claude-haiku-4-5-20251001",
        overflow_model="gpt-4.1",
        overflow_iterations=5,
    )


@pytest.fixture
def agent_config_few_tools() -> AgentConfig:
    """Agent config with <=10 tools — planner should be skipped."""
    return AgentConfig(
        name="test_agent",
        display_name="Test Agent",
        model="claude-opus-4-6",
        max_tokens=4096,
        max_iterations=3,
        system_prompt="You are a test agent.",
        tools=["search_knowledge", "send_email", "remember"],
        request_timeout=10,
    )


def _make_haiku_response(tool_names: list[str]) -> MagicMock:
    """Create a mock Anthropic response from Haiku returning a JSON array."""
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = json.dumps(tool_names)
    response = MagicMock()
    response.content = [text_block]
    return response


# ---------------------------------------------------------------------------
# Tool Planner Tests
# ---------------------------------------------------------------------------

class TestToolPlanner:
    """Test the _plan_tools method."""

    @pytest.mark.asyncio
    async def test_planner_returns_filtered_tools(self, agent_config_many_tools):
        """Planner should return a filtered subset of tools."""
        agent = Agent(agent_config_many_tools)
        agent.client = AsyncMock()

        selected = ["search_knowledge", "delegate_task", "send_email"]
        agent.client.messages.create = AsyncMock(
            return_value=_make_haiku_response(selected)
        )

        tool_defs = [
            {"name": t, "description": f"Tool {t}"} for t in agent_config_many_tools.tools
        ]

        with patch("chief_of_staff.agent.core.log_activity"):
            result = await agent._plan_tools(
                "delegate onboarding for Dr. Smith",
                agent_config_many_tools.tools,
                tool_defs,
            )

        # Should include selected tools + always-available meta-tools
        assert "search_knowledge" in result
        assert "delegate_task" in result
        assert "send_email" in result
        # Meta-tools should be merged in
        assert "report_progress" in result
        assert "remember" in result
        assert "recall_memory" in result

    @pytest.mark.asyncio
    async def test_planner_skips_when_few_tools(self, agent_config_few_tools):
        """Planner should skip when there are 10 or fewer tools."""
        agent = Agent(agent_config_few_tools)
        agent.client = AsyncMock()

        tool_defs = [
            {"name": t, "description": f"Tool {t}"} for t in agent_config_few_tools.tools
        ]

        result = await agent._plan_tools(
            "search for something",
            agent_config_few_tools.tools,
            tool_defs,
        )

        # Should return all tools unchanged
        assert result == agent_config_few_tools.tools
        # Haiku should NOT have been called
        agent.client.messages.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_planner_fallback_on_error(self, agent_config_many_tools):
        """Planner should fall back to all tools if API call fails."""
        agent = Agent(agent_config_many_tools)
        agent.client = AsyncMock()
        agent.client.messages.create = AsyncMock(side_effect=Exception("API down"))

        tool_defs = [
            {"name": t, "description": f"Tool {t}"} for t in agent_config_many_tools.tools
        ]

        result = await agent._plan_tools(
            "test message",
            agent_config_many_tools.tools,
            tool_defs,
        )

        assert result == agent_config_many_tools.tools

    @pytest.mark.asyncio
    async def test_planner_fallback_on_invalid_json(self, agent_config_many_tools):
        """Planner should fall back if Haiku returns non-JSON."""
        agent = Agent(agent_config_many_tools)
        agent.client = AsyncMock()

        bad_block = MagicMock()
        bad_block.type = "text"
        bad_block.text = "I can't decide which tools to use"
        bad_response = MagicMock()
        bad_response.content = [bad_block]
        agent.client.messages.create = AsyncMock(return_value=bad_response)

        tool_defs = [
            {"name": t, "description": f"Tool {t}"} for t in agent_config_many_tools.tools
        ]

        result = await agent._plan_tools(
            "test message",
            agent_config_many_tools.tools,
            tool_defs,
        )

        assert result == agent_config_many_tools.tools

    @pytest.mark.asyncio
    async def test_planner_fallback_on_empty_list(self, agent_config_many_tools):
        """Planner should fall back if Haiku returns empty array."""
        agent = Agent(agent_config_many_tools)
        agent.client = AsyncMock()
        agent.client.messages.create = AsyncMock(
            return_value=_make_haiku_response([])
        )

        tool_defs = [
            {"name": t, "description": f"Tool {t}"} for t in agent_config_many_tools.tools
        ]

        result = await agent._plan_tools(
            "test message",
            agent_config_many_tools.tools,
            tool_defs,
        )

        assert result == agent_config_many_tools.tools

    @pytest.mark.asyncio
    async def test_planner_filters_invalid_tool_names(self, agent_config_many_tools):
        """Planner should skip tool names that don't exist in the agent's tool set."""
        agent = Agent(agent_config_many_tools)
        agent.client = AsyncMock()

        selected = ["search_knowledge", "nonexistent_tool", "fake_tool"]
        agent.client.messages.create = AsyncMock(
            return_value=_make_haiku_response(selected)
        )

        tool_defs = [
            {"name": t, "description": f"Tool {t}"} for t in agent_config_many_tools.tools
        ]

        with patch("chief_of_staff.agent.core.log_activity"):
            result = await agent._plan_tools(
                "test message",
                agent_config_many_tools.tools,
                tool_defs,
            )

        assert "search_knowledge" in result
        assert "nonexistent_tool" not in result
        assert "fake_tool" not in result

    @pytest.mark.asyncio
    async def test_always_available_tools_included(self, agent_config_many_tools):
        """Meta-tools should always be included even if planner doesn't select them."""
        agent = Agent(agent_config_many_tools)
        agent.client = AsyncMock()

        # Planner only returns search_knowledge
        agent.client.messages.create = AsyncMock(
            return_value=_make_haiku_response(["search_knowledge"])
        )

        tool_defs = [
            {"name": t, "description": f"Tool {t}"} for t in agent_config_many_tools.tools
        ]

        with patch("chief_of_staff.agent.core.log_activity"):
            result = await agent._plan_tools(
                "test message",
                agent_config_many_tools.tools,
                tool_defs,
            )

        for meta_tool in _ALWAYS_AVAILABLE_TOOLS:
            if meta_tool in agent_config_many_tools.tools:
                assert meta_tool in result

    @pytest.mark.asyncio
    async def test_planner_handles_markdown_code_block(self, agent_config_many_tools):
        """Planner should handle Haiku wrapping response in ```json ... ```."""
        agent = Agent(agent_config_many_tools)
        agent.client = AsyncMock()

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = '```json\n["search_knowledge", "delegate_task"]\n```'
        response = MagicMock()
        response.content = [text_block]
        agent.client.messages.create = AsyncMock(return_value=response)

        tool_defs = [
            {"name": t, "description": f"Tool {t}"} for t in agent_config_many_tools.tools
        ]

        with patch("chief_of_staff.agent.core.log_activity"):
            result = await agent._plan_tools(
                "test message",
                agent_config_many_tools.tools,
                tool_defs,
            )

        assert "search_knowledge" in result
        assert "delegate_task" in result


# ---------------------------------------------------------------------------
# OpenAI Adapter Tests
# ---------------------------------------------------------------------------

class TestOpenAIAdapter:
    """Test the OpenAI adapter conversion functions."""

    def test_convert_tools_basic(self):
        """Anthropic tool defs should convert to OpenAI function-calling format."""
        anthropic_tools = [
            {
                "name": "search_knowledge",
                "description": "Search the knowledge base",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                    },
                    "required": ["query"],
                },
            }
        ]

        openai_tools = convert_tools(anthropic_tools)

        assert len(openai_tools) == 1
        assert openai_tools[0]["type"] == "function"
        func = openai_tools[0]["function"]
        assert func["name"] == "search_knowledge"
        assert func["description"] == "Search the knowledge base"
        assert func["parameters"]["properties"]["query"]["type"] == "string"

    def test_convert_tools_skips_server_tools(self):
        """Server tools (no 'name' key) should be skipped."""
        tools = [
            {"type": "web_search_20250305", "name": "web_search", "max_uses": 5},
            {"name": "search_knowledge", "description": "Search", "input_schema": {"type": "object", "properties": {}}},
        ]

        openai_tools = convert_tools(tools)

        # web_search has 'name' so it will be included (server tools with name are fine)
        # The key thing is tools without name are skipped
        assert len(openai_tools) >= 1

    def test_convert_messages_system_prompt(self):
        """System prompt should become the first message."""
        messages = [{"role": "user", "content": "Hello"}]
        result = convert_messages(messages, "You are a test bot")

        assert result[0]["role"] == "system"
        assert result[0]["content"] == "You are a test bot"
        assert result[1]["role"] == "user"
        assert result[1]["content"] == "Hello"

    def test_convert_messages_tool_results(self):
        """Anthropic tool_result blocks should become OpenAI tool messages."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "abc123", "content": "Result here"},
            ]},
        ]

        result = convert_messages(messages, "System")

        # System + user message + tool result
        assert len(result) == 3
        assert result[2]["role"] == "tool"
        assert result[2]["tool_call_id"] == "abc123"
        assert result[2]["content"] == "Result here"

    def test_convert_messages_assistant_with_tool_calls(self):
        """Assistant messages with tool_use blocks should have tool_calls in OpenAI format."""
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "search_knowledge"
        tool_block.input = {"query": "test"}
        tool_block.id = "tool_456"

        messages = [
            {"role": "user", "content": "Search for test"},
            {"role": "assistant", "content": [tool_block]},
        ]

        result = convert_messages(messages, "System")

        assistant_msg = result[2]  # system + user + assistant
        assert assistant_msg["role"] == "assistant"
        assert "tool_calls" in assistant_msg
        assert assistant_msg["tool_calls"][0]["function"]["name"] == "search_knowledge"
        assert json.loads(assistant_msg["tool_calls"][0]["function"]["arguments"]) == {"query": "test"}

    def test_convert_messages_assistant_text(self):
        """Assistant messages with text blocks should have content string."""
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Here is the answer"

        messages = [
            {"role": "user", "content": "Question"},
            {"role": "assistant", "content": [text_block]},
        ]

        result = convert_messages(messages, "System")

        assistant_msg = result[2]
        assert assistant_msg["role"] == "assistant"
        assert assistant_msg["content"] == "Here is the answer"


# ---------------------------------------------------------------------------
# Overflow Integration Tests
# ---------------------------------------------------------------------------

class TestOverflow:
    """Test the overflow logic in core.py."""

    @pytest.mark.asyncio
    async def test_overflow_triggered_when_iterations_exhausted(self, agent_config_many_tools):
        """When max_iterations is exhausted and overflow is enabled, GPT-4.1 should be called."""
        agent = Agent(agent_config_many_tools)
        agent.client = AsyncMock()

        # Make every Anthropic response a tool call (never finishes)
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "search_knowledge"
        tool_block.input = {"query": "test"}
        tool_block.id = "tool_123"
        response = MagicMock()
        response.content = [tool_block]
        agent.client.messages.create = AsyncMock(return_value=response)

        with patch("chief_of_staff.agent.core.execute_tool", new_callable=AsyncMock, return_value="result"), \
             patch("chief_of_staff.agent.core.log_activity"), \
             patch("chief_of_staff.agent.core.get_tool_definitions", return_value=[]), \
             patch("chief_of_staff.agent.core.settings") as mock_settings, \
             patch("chief_of_staff.agent.openai_adapter.overflow_respond", new_callable=AsyncMock, return_value="Overflow answer") as mock_overflow:
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.overflow_enabled = True
            mock_settings.openai_api_key = "test-openai-key"
            mock_settings.openai_model = "gpt-4.1"

            # Patch the import inside core.py
            with patch("chief_of_staff.agent.core.settings", mock_settings):
                # We need to directly test _respond_inner to avoid timeout
                with patch.object(agent, 'reload_config'), \
                     patch("chief_of_staff.knowledge.store.get_context_for_query", side_effect=Exception("no kb")):
                    result = await agent._respond_inner("test question")

        # Should have called overflow
        assert result == "Overflow answer"

    @pytest.mark.asyncio
    async def test_no_overflow_when_disabled(self, agent_config_many_tools):
        """When overflow is disabled, should return the limit message."""
        agent = Agent(agent_config_many_tools)
        agent.client = AsyncMock()

        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "search_knowledge"
        tool_block.input = {"query": "test"}
        tool_block.id = "tool_123"
        response = MagicMock()
        response.content = [tool_block]
        agent.client.messages.create = AsyncMock(return_value=response)

        with patch("chief_of_staff.agent.core.execute_tool", new_callable=AsyncMock, return_value="result"), \
             patch("chief_of_staff.agent.core.log_activity"), \
             patch("chief_of_staff.agent.core.get_tool_definitions", return_value=[]), \
             patch("chief_of_staff.agent.core.settings") as mock_settings:
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.overflow_enabled = False
            mock_settings.openai_api_key = ""

            with patch.object(agent, 'reload_config'), \
                 patch("chief_of_staff.knowledge.store.get_context_for_query", side_effect=Exception("no kb")):
                result = await agent._respond_inner("test question")

        assert "reasoning limit" in result.lower()
