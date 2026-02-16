"""Tests for async sub-agent runtime tools."""

from __future__ import annotations

import json
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from chief_of_staff.agent.skills.delegation import execute, _ACTIVE_SUBAGENT_TASKS


@pytest.mark.asyncio
async def test_spawn_sub_agent_task_creates_run_and_returns_id():
    """spawn_sub_agent_task should persist a run and return acceptance text."""
    _ACTIVE_SUBAGENT_TASKS.clear()
    fake_ctx = SimpleNamespace(channel="discord", user_id="u1", session_id="s1")
    fake_registry = SimpleNamespace(
        get=lambda _name: SimpleNamespace(permissions={"max_delegation_depth": 3})
    )
    original_create_task = asyncio.create_task
    spawned: list[asyncio.Task] = []

    def _capture_task(coro):
        task = original_create_task(coro)
        spawned.append(task)
        return task

    with (
        patch("chief_of_staff.agent.request_context.get_request_context", return_value=fake_ctx),
        patch("chief_of_staff.agent.registry.get_registry", return_value=fake_registry),
        patch("chief_of_staff.knowledge.database.create_sub_agent_run") as create_run,
        patch("chief_of_staff.agent.skills.delegation._run_spawned_subagent", return_value=None),
        patch("chief_of_staff.agent.skills.delegation.asyncio.create_task", side_effect=_capture_task),
        patch("chief_of_staff.agent.activity.log_activity"),
    ):
        result = await execute(
            "spawn_sub_agent_task",
            {"agent_name": "onboarding", "task": "Draft a welcome packet"},
            "chief_of_staff",
        )
        if spawned:
            await asyncio.gather(*spawned)

    assert "Spawned sub-agent run" in result
    create_run.assert_called_once()


@pytest.mark.asyncio
async def test_list_sub_agent_tasks_returns_json():
    """list_sub_agent_tasks should serialize DB records."""
    runs = [
        {"id": "run-1", "status": "completed", "child_agent": "onboarding"},
        {"id": "run-2", "status": "running", "child_agent": "onboarding"},
    ]
    with patch("chief_of_staff.knowledge.database.list_sub_agent_runs", return_value=runs):
        result = await execute("list_sub_agent_tasks", {"limit": 2}, "chief_of_staff")
    parsed = json.loads(result)
    assert len(parsed) == 2
    assert parsed[0]["id"] == "run-1"


@pytest.mark.asyncio
async def test_cancel_sub_agent_task_active_task():
    """cancel_sub_agent_task should cancel active in-memory task handles."""
    run_id = "run-active"
    task = MagicMock()
    task.done.return_value = False
    _ACTIVE_SUBAGENT_TASKS[run_id] = task

    with patch("chief_of_staff.knowledge.database.mark_sub_agent_run_cancelled") as mark_cancelled:
        result = await execute("cancel_sub_agent_task", {"run_id": run_id}, "chief_of_staff")

    assert "Cancellation requested" in result
    task.cancel.assert_called_once()
    mark_cancelled.assert_called_once()
    _ACTIVE_SUBAGENT_TASKS.clear()
