"""Tests for orchestration skill (planning, execution, and scaffolding)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from chief_of_staff.agent.skills.orchestration import execute


@pytest.mark.asyncio
async def test_create_and_execute_task_plan_with_tool_step():
    """A created plan can be executed when steps use direct tool calls."""
    created = await execute(
        "create_task_plan",
        {
            "goal": "Send outreach then save memory",
            "tasks": [
                {
                    "description": "Search context",
                    "tool_name": "search_knowledge",
                    "tool_args": {"query": "outreach"},
                }
            ],
        },
        "chief_of_staff",
    )
    assert "Created plan" in created
    plan_id = created.split("Created plan ", 1)[1].split(" ", 1)[0]

    with patch("chief_of_staff.agent.tools.execute_tool", new=AsyncMock(return_value="ok")):
        result = await execute("execute_task_plan", {"plan_id": plan_id}, "chief_of_staff")

    assert "execution finished" in result
    assert '"status": "completed"' in result


@pytest.mark.asyncio
async def test_scaffold_skill_writes_file_and_attaches_to_agent(tmp_path):
    """scaffold_skill creates a module and appends it to target agent skills."""
    output_path = tmp_path / "follow_up.py"
    config = SimpleNamespace(
        skills=[],
        to_yaml=lambda _p: None,
    )

    class DummyRegistry:
        def get(self, name: str):
            return config if name == "chief_of_staff" else None

    with (
        patch("chief_of_staff.agent.skills.orchestration._skill_path", return_value=output_path),
        patch("chief_of_staff.agent.skills.get_skill_registry") as mock_get_skill_registry,
        patch("chief_of_staff.agent.registry.get_registry", return_value=DummyRegistry()),
    ):
        mock_get_skill_registry.return_value.reload = lambda: None
        result = await execute(
            "scaffold_skill",
            {
                "skill_name": "follow_up",
                "purpose": "Handle follow-ups",
                "tools": [{"name": "send_follow_up", "description": "Send a follow-up message"}],
                "attach_to_agent": "chief_of_staff",
            },
            "chief_of_staff",
        )

    assert "Created skill scaffold" in result
    assert "Attached skill 'follow_up'" in result
    assert output_path.exists()
    assert "SKILL_NAME = \"follow_up\"" in output_path.read_text()
    assert "follow_up" in config.skills
