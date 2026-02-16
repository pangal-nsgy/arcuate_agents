"""Tests for live progress streaming to Discord."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chief_of_staff.agent.request_context import (
    RequestContext,
    _PROGRESS_MIN_INTERVAL,
    emit_progress,
    get_request_context,
    reset_request_context,
    set_request_context,
)


# ---------------------------------------------------------------------------
# emit_progress basics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emit_progress_calls_callback():
    """emit_progress invokes the progress_callback with the message."""
    cb = AsyncMock()
    token = set_request_context(channel="discord", user_id="u1", session_id="s1", progress_callback=cb)
    try:
        await emit_progress("Searching knowledge base...")
        cb.assert_awaited_once_with("Searching knowledge base...")
    finally:
        reset_request_context(token)


@pytest.mark.asyncio
async def test_emit_progress_no_callback():
    """emit_progress is a no-op when no callback is set (non-Discord channels)."""
    token = set_request_context(channel="api", user_id="u1", session_id="s1")
    try:
        # Should not raise
        await emit_progress("This goes nowhere")
    finally:
        reset_request_context(token)


@pytest.mark.asyncio
async def test_emit_progress_swallows_errors():
    """emit_progress never raises, even if the callback throws."""
    cb = AsyncMock(side_effect=Exception("Discord API error"))
    token = set_request_context(channel="discord", user_id="u1", session_id="s1", progress_callback=cb)
    try:
        await emit_progress("This will fail")
        # Should reach here without raising
    finally:
        reset_request_context(token)


# ---------------------------------------------------------------------------
# Throttling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emit_progress_throttles_rapid_calls():
    """Rapid calls within _PROGRESS_MIN_INTERVAL are suppressed."""
    cb = AsyncMock()
    token = set_request_context(channel="discord", user_id="u1", session_id="s1", progress_callback=cb)
    try:
        await emit_progress("First message")
        await emit_progress("Second message (should be throttled)")
        await emit_progress("Third message (should be throttled)")

        assert cb.await_count == 1
        cb.assert_awaited_once_with("First message")
    finally:
        reset_request_context(token)


@pytest.mark.asyncio
async def test_emit_progress_sends_after_interval():
    """After the throttle interval, a new message gets through."""
    cb = AsyncMock()
    token = set_request_context(channel="discord", user_id="u1", session_id="s1", progress_callback=cb)
    try:
        await emit_progress("First message")
        assert cb.await_count == 1

        # Simulate passage of time by manipulating _last_progress_time
        ctx = get_request_context()
        ctx._last_progress_time = time.time() - _PROGRESS_MIN_INTERVAL - 0.1

        await emit_progress("Second message (should go through)")
        assert cb.await_count == 2
    finally:
        reset_request_context(token)


# ---------------------------------------------------------------------------
# core.py progress emissions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_respond_emits_progress_at_tool_planning(agent_config, mock_anthropic_response):
    """Agent.respond() emits progress during tool planning."""
    from chief_of_staff.agent.core import Agent

    agent = Agent(agent_config)
    agent.client = AsyncMock()
    agent.client.messages.create = AsyncMock(
        return_value=mock_anthropic_response("Done!")
    )

    cb = AsyncMock()

    with patch("chief_of_staff.agent.core.get_registry") as mock_reg:
        mock_reg.return_value.get.return_value = agent.config
        with patch("chief_of_staff.knowledge.store.get_context_for_query", return_value=""):
            result = await agent.respond(
                "What is Arcuate?",
                progress_callback=cb,
            )

    assert "Done!" in result
    # Should have emitted at least "Planning approach..."
    messages = [call.args[0] for call in cb.call_args_list]
    assert any("Planning" in m for m in messages)


@pytest.mark.asyncio
async def test_respond_emits_progress_on_tool_call(agent_config, mock_anthropic_response):
    """Agent.respond() emits progress with tool display name during tool calls."""
    from chief_of_staff.agent.core import Agent

    agent_config.tools = ["search_knowledge"]
    agent = Agent(agent_config)

    # First response: tool call, second: final text
    tool_resp = mock_anthropic_response(
        tool_calls=[{"name": "search_knowledge", "input": {"query": "test"}, "id": "t1"}]
    )
    text_resp = mock_anthropic_response("Here are the results.")

    agent.client = AsyncMock()
    agent.client.messages.create = AsyncMock(side_effect=[tool_resp, text_resp])

    # Disable throttling so all progress messages come through
    cb = AsyncMock()

    with patch("chief_of_staff.agent.core.get_registry") as mock_reg:
        mock_reg.return_value.get.return_value = agent.config
        with patch("chief_of_staff.knowledge.store.get_context_for_query", return_value=""):
            with patch("chief_of_staff.agent.core.execute_tool", new_callable=AsyncMock, return_value="results"):
                with patch("chief_of_staff.agent.request_context._PROGRESS_MIN_INTERVAL", 0):
                    result = await agent.respond(
                        "Search for something",
                        progress_callback=cb,
                    )

    assert "results" in result.lower() or "Here are" in result
    messages = [call.args[0] for call in cb.call_args_list]
    assert any("Searching knowledge base" in m for m in messages)


# ---------------------------------------------------------------------------
# report_progress tool forwards to Discord
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_progress_forwards_to_emit():
    """The report_progress execution tool forwards status to emit_progress."""
    from chief_of_staff.agent.skills.execution import _report_progress

    cb = AsyncMock()
    token = set_request_context(channel="discord", user_id="u1", session_id="s1", progress_callback=cb)
    try:
        result = await _report_progress(
            {"status": "Scraped 3/10 pages", "step": 3, "total_steps": 10},
            "test_agent",
        )
        assert "3/10" in result
        # Should have forwarded to the callback
        cb.assert_awaited_once()
        forwarded = cb.call_args.args[0]
        assert "Scraped 3/10 pages" in forwarded
    finally:
        reset_request_context(token)


@pytest.mark.asyncio
async def test_report_progress_works_without_callback():
    """report_progress still works when no progress callback is set."""
    from chief_of_staff.agent.skills.execution import _report_progress

    token = set_request_context(channel="api", user_id="u1", session_id="s1")
    try:
        result = await _report_progress({"status": "Working..."}, "test_agent")
        assert "Working" in result
    finally:
        reset_request_context(token)


# ---------------------------------------------------------------------------
# Delegation propagates progress callback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delegation_propagates_callback():
    """delegate_task passes the progress_callback to the sub-agent."""
    from chief_of_staff.agent.skills.delegation import execute as delegation_execute

    cb = AsyncMock()
    token = set_request_context(channel="discord", user_id="u1", session_id="s1", progress_callback=cb)

    mock_sub_agent = MagicMock()
    mock_sub_agent.config.display_name = "Onboarding Specialist"
    mock_sub_agent.respond = AsyncMock(return_value="Task completed!")

    try:
        with patch("chief_of_staff.agent.core.get_agent_by_name", return_value=mock_sub_agent):
            with patch("chief_of_staff.agent.skills.delegation._get_delegation_limit", return_value=(0, 2)):
                result = await delegation_execute(
                    "delegate_task",
                    {"agent_name": "onboarding", "task": "Review emails"},
                    "chief_of_staff",
                )

        assert "Task completed!" in result

        # Sub-agent.respond() should have received progress_callback=cb
        _, kwargs = mock_sub_agent.respond.call_args
        assert kwargs.get("progress_callback") is cb

        # Should have emitted delegation progress
        messages = [call.args[0] for call in cb.call_args_list]
        assert any("Delegating" in m for m in messages)
    finally:
        reset_request_context(token)


@pytest.mark.asyncio
async def test_delegation_works_without_callback():
    """delegate_task works when no progress callback is set."""
    from chief_of_staff.agent.skills.delegation import execute as delegation_execute

    token = set_request_context(channel="api", user_id="u1", session_id="s1")

    mock_sub_agent = MagicMock()
    mock_sub_agent.config.display_name = "Onboarding Specialist"
    mock_sub_agent.respond = AsyncMock(return_value="Done!")

    try:
        with patch("chief_of_staff.agent.core.get_agent_by_name", return_value=mock_sub_agent):
            with patch("chief_of_staff.agent.skills.delegation._get_delegation_limit", return_value=(0, 2)):
                result = await delegation_execute(
                    "delegate_task",
                    {"agent_name": "onboarding", "task": "Review emails"},
                    "chief_of_staff",
                )

        assert "Done!" in result
        _, kwargs = mock_sub_agent.respond.call_args
        assert kwargs.get("progress_callback") is None
    finally:
        reset_request_context(token)
