"""Tests for structured error handling — tools return strings, never exceptions."""

from __future__ import annotations

from unittest.mock import patch, AsyncMock

import pytest

from chief_of_staff.agent.tools import execute_tool


@pytest.mark.asyncio
async def test_send_sms_error_returns_string():
    """SMS tool failure returns error string instead of raising."""
    with patch(
        "chief_of_staff.communication.sms.send_sms",
        new_callable=AsyncMock,
        side_effect=ValueError("Invalid phone number"),
    ):
        result = await execute_tool("send_sms", {"to": "invalid", "message": "hi"}, agent_name="test")
    assert "error" in result.lower()
    assert "ValueError" in result
    assert "Invalid phone number" in result


@pytest.mark.asyncio
async def test_send_email_error_returns_string():
    """Email tool failure returns error string instead of raising."""
    with patch(
        "chief_of_staff.communication.email.send_email",
        new_callable=AsyncMock,
        side_effect=ConnectionError("SMTP down"),
    ):
        result = await execute_tool(
            "send_email",
            {"to": "test@test.com", "subject": "Hi", "body": "Hello"},
            agent_name="test",
        )
    assert "error" in result.lower()
    assert "ConnectionError" in result


@pytest.mark.asyncio
async def test_remember_error_returns_string():
    """Memory tool failure returns error string instead of raising."""
    with patch(
        "chief_of_staff.agent.memory.append_memory_safe",
        new_callable=AsyncMock,
        side_effect=OSError("Disk full"),
    ):
        result = await execute_tool(
            "remember",
            {"content": "test memory", "category": "general"},
            agent_name="test",
        )
    assert "error" in result.lower()
    assert "OSError" in result


@pytest.mark.asyncio
async def test_error_message_suggests_alternative():
    """Error messages include 'Try a different approach' guidance."""
    with patch(
        "chief_of_staff.knowledge.store.search",
        side_effect=RuntimeError("vector store offline"),
    ):
        result = await execute_tool("search_knowledge", {"query": "test"}, agent_name="test")
    assert "different approach" in result.lower()
