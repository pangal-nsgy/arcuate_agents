"""Tests for tool dispatch and error wrapping."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from chief_of_staff.agent.tools import execute_tool


@pytest.mark.asyncio
async def test_unknown_tool_returns_string():
    """Calling an unknown tool returns a string, not an exception."""
    result = await execute_tool("nonexistent_tool", {}, agent_name="test")
    assert "Unknown tool" in result or "error" in result.lower()


@pytest.mark.asyncio
async def test_search_knowledge_no_results():
    """search_knowledge with no results returns a message."""
    with patch("chief_of_staff.knowledge.store.search", return_value=[]):
        result = await execute_tool("search_knowledge", {"query": "xyz"}, agent_name="test")
    assert "No results" in result


@pytest.mark.asyncio
async def test_tool_error_returns_string():
    """A tool that raises an exception returns an error string, not an exception."""
    with patch("chief_of_staff.knowledge.store.search", side_effect=RuntimeError("DB crashed")):
        result = await execute_tool("search_knowledge", {"query": "test"}, agent_name="test")
    assert "error" in result.lower()
    assert "RuntimeError" in result
    assert "DB crashed" in result


@pytest.mark.asyncio
async def test_draft_document_returns_json():
    """draft_document returns a JSON string."""
    result = await execute_tool(
        "draft_document",
        {"title": "Test Doc", "content": "Hello", "doc_type": "memo"},
        agent_name="test",
    )
    assert "draft_created" in result
    assert "Test Doc" in result
