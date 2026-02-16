"""Tests for async sub-agent runtime tools."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from chief_of_staff.agent.skills.delegation import execute
from chief_of_staff.agent.subagent_runtime import _ACTIVE_SUBAGENT_TASKS, recover_pending_sub_agent_runs


@pytest.mark.asyncio
async def test_spawn_sub_agent_task_creates_run_and_returns_id():
    """spawn_sub_agent_task should persist a run and return acceptance text."""
    fake_ctx = SimpleNamespace(channel="discord", user_id="u1", session_id="s1")
    fake_registry = SimpleNamespace(get=lambda _name: SimpleNamespace(permissions={"max_delegation_depth": 3}))

    with (
        patch("chief_of_staff.agent.request_context.get_request_context", return_value=fake_ctx),
        patch("chief_of_staff.agent.registry.get_registry", return_value=fake_registry),
        patch("chief_of_staff.agent.subagent_runtime.spawn_sub_agent_run", return_value="run-1234") as spawn_run,
        patch("chief_of_staff.agent.activity.log_activity"),
    ):
        result = await execute(
            "spawn_sub_agent_task",
            {"agent_name": "onboarding", "task": "Draft a welcome packet"},
            "chief_of_staff",
        )

    assert "Spawned sub-agent run" in result
    spawn_run.assert_called_once()


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
    with patch("chief_of_staff.agent.subagent_runtime.cancel_sub_agent_run", return_value="cancel_requested"):
        result = await execute("cancel_sub_agent_task", {"run_id": run_id}, "chief_of_staff")

    assert "Cancellation requested" in result


def test_recover_pending_sub_agent_runs_enqueues_tasks():
    """Recovery should enqueue queued/running rows that are not already active."""
    _ACTIVE_SUBAGENT_TASKS.clear()
    queued = [{"id": "run-q", "parent_agent": "chief_of_staff", "child_agent": "onboarding", "task": "task q", "requester_channel": "discord"}]
    running = [{"id": "run-r", "parent_agent": "chief_of_staff", "child_agent": "onboarding", "task": "task r", "requester_channel": "discord"}]

    with (
        patch("chief_of_staff.agent.subagent_runtime.list_sub_agent_runs", side_effect=[queued, running]),
        patch("chief_of_staff.agent.subagent_runtime._run_subagent", return_value=None),
        patch("chief_of_staff.agent.subagent_runtime.asyncio.create_task") as create_task,
    ):
        recovered = recover_pending_sub_agent_runs()

    assert recovered == 2
    assert create_task.call_count == 2
