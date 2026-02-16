"""Tests for the skill registry and skill modules."""

from __future__ import annotations

from unittest.mock import patch, AsyncMock

import pytest

from chief_of_staff.agent.skills import SkillRegistry, get_skill_registry


class TestSkillRegistry:
    """Test the SkillRegistry class."""

    def test_loads_all_skill_modules(self):
        """Registry should auto-load all 9 skill modules."""
        registry = SkillRegistry()
        registry._ensure_loaded()
        assert len(registry._skills) == 9
        assert "knowledge" in registry._skills
        assert "communication" in registry._skills
        assert "meetings" in registry._skills
        assert "self_mod" in registry._skills
        assert "memory" in registry._skills
        assert "delegation" in registry._skills
        assert "code_ops" in registry._skills
        assert "orchestration" in registry._skills
        assert "execution" in registry._skills

    def test_all_25_tools_mapped(self):
        """All 25 tools should be mapped to their skill modules."""
        registry = SkillRegistry()
        registry._ensure_loaded()
        assert len(registry._tool_map) == 25
        expected = [
            "search_knowledge", "list_recent_emails", "search_meetings",
            "send_sms", "send_email", "draft_document",
            "send_meeting_bot",
            "show_current_prompt", "update_own_instructions", "update_system_prompt", "update_triage_config",
            "remember", "recall_memory",
            "create_sub_agent", "delegate_task",
            "read_own_code", "edit_own_code", "deploy_changes",
            "create_task_plan", "execute_task_plan", "scaffold_skill",
            "run_python", "fetch_webpage", "install_package", "report_progress",
        ]
        for tool in expected:
            assert tool in registry._tool_map, f"Tool '{tool}' not in registry"

    def test_get_tool_definitions(self):
        """get_tool_definitions returns correct definitions for requested tools."""
        registry = SkillRegistry()
        defs = registry.get_tool_definitions(["search_knowledge", "send_email"])
        assert len(defs) == 2
        names = {d["name"] for d in defs}
        assert names == {"search_knowledge", "send_email"}

    def test_get_tool_definitions_ignores_unknown(self):
        """Unknown tool names are silently skipped."""
        registry = SkillRegistry()
        defs = registry.get_tool_definitions(["search_knowledge", "nonexistent"])
        assert len(defs) == 1

    def test_resolve_skills_by_skill_name(self):
        """Resolving a skill name returns all its tools."""
        registry = SkillRegistry()
        tools = registry.resolve_skills(["knowledge"])
        assert "search_knowledge" in tools
        assert "list_recent_emails" in tools
        assert "search_meetings" in tools

    def test_resolve_skills_by_tool_name(self):
        """Resolving an individual tool name returns just that tool."""
        registry = SkillRegistry()
        tools = registry.resolve_skills(["send_email"])
        assert tools == ["send_email"]

    def test_resolve_skills_mixed(self):
        """Mixed skill names and tool names are resolved correctly."""
        registry = SkillRegistry()
        tools = registry.resolve_skills(["knowledge", "send_email"])
        assert "search_knowledge" in tools
        assert "list_recent_emails" in tools
        assert "search_meetings" in tools
        assert "send_email" in tools

    def test_resolve_skills_deduplicates(self):
        """Duplicate tool names from overlapping refs are deduplicated."""
        registry = SkillRegistry()
        tools = registry.resolve_skills(["knowledge", "search_knowledge"])
        assert tools.count("search_knowledge") == 1

    def test_get_all_tool_definitions(self):
        """get_all_tool_definitions returns all 25 tools."""
        registry = SkillRegistry()
        all_defs = registry.get_all_tool_definitions()
        assert len(all_defs) == 25


class TestSkillExecution:
    """Test tool execution through the skill registry."""

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        """Unknown tool returns an error string."""
        registry = SkillRegistry()
        result = await registry.execute_tool("nonexistent", {}, "test")
        assert "Unknown tool" in result

    @pytest.mark.asyncio
    async def test_knowledge_search_dispatches(self):
        """search_knowledge dispatches to the knowledge skill module."""
        registry = SkillRegistry()
        with patch("chief_of_staff.knowledge.store.search", return_value=[]):
            result = await registry.execute_tool(
                "search_knowledge", {"query": "test"}, "test"
            )
        assert "No results" in result

    @pytest.mark.asyncio
    async def test_draft_document_dispatches(self):
        """draft_document dispatches to the communication skill module."""
        registry = SkillRegistry()
        result = await registry.execute_tool(
            "draft_document",
            {"title": "Test", "content": "Hello", "doc_type": "memo"},
            "test",
        )
        assert "draft_created" in result

    @pytest.mark.asyncio
    async def test_show_current_prompt_dispatches(self):
        """show_current_prompt returns the current base prompt text."""
        registry = SkillRegistry()
        with patch("chief_of_staff.agent.registry.AgentRegistry.get") as mock_get:
            mock_get.return_value = type(
                "Cfg",
                (),
                {"system_prompt": "Base prompt", "build_system_prompt": lambda self: "Effective prompt"},
            )()
            result = await registry.execute_tool("show_current_prompt", {}, "chief_of_staff")
        assert "Base system_prompt" in result
        assert "Base prompt" in result

    @pytest.mark.asyncio
    async def test_remember_dispatches(self):
        """remember dispatches to the memory skill module."""
        registry = SkillRegistry()
        with patch(
            "chief_of_staff.agent.memory.append_memory_safe",
            new_callable=AsyncMock,
        ):
            result = await registry.execute_tool(
                "remember",
                {"content": "test fact", "category": "general"},
                "test",
            )
        assert "Remembered" in result
