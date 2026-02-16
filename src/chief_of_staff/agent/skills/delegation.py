"""Delegation skill — create sub-agents and delegate tasks."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

SKILL_NAME = "delegation"

_ACTIVE_SUBAGENT_TASKS: dict[str, asyncio.Task] = {}

TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "create_sub_agent": {
        "name": "create_sub_agent",
        "description": "Create a new specialized sub-agent. Use when a recurring task needs a dedicated agent with a focused system prompt and specific tools.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Agent name (snake_case, e.g., lead_scorer)"},
                "display_name": {"type": "string", "description": "Human-readable name"},
                "system_prompt": {"type": "string", "description": "System prompt for the sub-agent"},
                "tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tools the sub-agent can use",
                },
            },
            "required": ["name", "display_name", "system_prompt"],
        },
    },
    "delegate_task": {
        "name": "delegate_task",
        "description": "Delegate a task to a sub-agent. The sub-agent runs synchronously and returns a result.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "Name of the sub-agent to delegate to"},
                "task": {"type": "string", "description": "The task to delegate"},
            },
            "required": ["agent_name", "task"],
        },
    },
    "spawn_sub_agent_task": {
        "name": "spawn_sub_agent_task",
        "description": "Spawn a sub-agent task asynchronously. Returns immediately with a run ID. Use list_sub_agent_tasks to track status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "Target sub-agent name"},
                "task": {"type": "string", "description": "Task for the sub-agent"},
                "announce_channel": {"type": "string", "description": "Discord channel name for completion notice"},
            },
            "required": ["agent_name", "task"],
        },
    },
    "list_sub_agent_tasks": {
        "name": "list_sub_agent_tasks",
        "description": "List recent sub-agent task runs and statuses for this parent agent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["queued", "running", "completed", "failed", "cancelled"],
                },
                "limit": {"type": "integer"},
            },
        },
    },
    "cancel_sub_agent_task": {
        "name": "cancel_sub_agent_task",
        "description": "Cancel a running sub-agent task by run ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
            },
            "required": ["run_id"],
        },
    },
}


def _get_delegation_limit(agent_name: str) -> tuple[int, int]:
    from chief_of_staff.agent.delegation_context import get_delegation_depth
    from chief_of_staff.agent.registry import get_registry

    caller_config = get_registry().get(agent_name)
    max_depth = int((caller_config.permissions or {}).get("max_delegation_depth", 1)) if caller_config else 1
    return get_delegation_depth(), max_depth


async def _announce_sub_agent_completion(
    run_id: str,
    child_agent: str,
    status: str,
    result_or_error: str,
    requester_channel: str,
    announce_channel: str,
) -> None:
    """Announce sub-agent completion back to the parent channel when possible."""
    if requester_channel != "discord":
        return

    from chief_of_staff.communication.discord_bot import send_to_channel

    short = result_or_error[:1200]
    message = (
        f"Sub-agent run `{run_id[:8]}` finished\n"
        f"- agent: `{child_agent}`\n"
        f"- status: `{status}`\n"
        f"- summary:\n{short}"
    )
    await send_to_channel(announce_channel, message)


async def _run_spawned_subagent(
    run_id: str,
    parent_agent: str,
    child_agent: str,
    task: str,
    requester_channel: str,
    announce_channel: str,
) -> None:
    """Execute an async sub-agent run under the sub-agent lane."""
    from chief_of_staff.agent.activity import log_activity, SUB_AGENT_SPAWN, ERROR
    from chief_of_staff.agent.core import get_agent_by_name
    from chief_of_staff.agent.delegation_context import enter_delegation, exit_delegation
    from chief_of_staff.agent.lanes import run_subagent_lane
    from chief_of_staff.knowledge.database import (
        mark_sub_agent_run_running,
        mark_sub_agent_run_completed,
        mark_sub_agent_run_failed,
        mark_sub_agent_run_cancelled,
    )

    sub_agent = get_agent_by_name(child_agent)
    if not sub_agent:
        mark_sub_agent_run_failed(run_id, f"Sub-agent '{child_agent}' not found.")
        await _announce_sub_agent_completion(
            run_id, child_agent, "failed", f"Sub-agent '{child_agent}' not found.", requester_channel, announce_channel
        )
        return

    mark_sub_agent_run_running(run_id)
    token = enter_delegation()
    try:
        result = await run_subagent_lane(
            sub_agent.respond(
                user_message=task,
                channel="delegation",
                user_id=parent_agent,
                session_id=run_id,
            )
        )
        mark_sub_agent_run_completed(run_id, result)
        log_activity(
            agent_name=parent_agent,
            action_type=SUB_AGENT_SPAWN,
            action_detail=f"Sub-agent run completed: {run_id}",
            metadata={"run_id": run_id, "child_agent": child_agent},
        )
        await _announce_sub_agent_completion(
            run_id, child_agent, "completed", result, requester_channel, announce_channel
        )
    except asyncio.CancelledError:
        mark_sub_agent_run_cancelled(run_id, "Cancelled by parent agent")
        await _announce_sub_agent_completion(
            run_id, child_agent, "cancelled", "Cancelled by parent agent.", requester_channel, announce_channel
        )
        raise
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        mark_sub_agent_run_failed(run_id, err)
        log_activity(
            agent_name=parent_agent,
            action_type=ERROR,
            action_detail=f"Sub-agent run failed: {run_id}",
            output_summary=err[:500],
            metadata={"run_id": run_id, "child_agent": child_agent},
        )
        await _announce_sub_agent_completion(
            run_id, child_agent, "failed", err, requester_channel, announce_channel
        )
    finally:
        exit_delegation(token)
        _ACTIVE_SUBAGENT_TASKS.pop(run_id, None)


async def execute(name: str, args: dict[str, Any], agent_name: str) -> str:
    """Execute a delegation tool. May raise — caller handles exceptions."""
    if name == "create_sub_agent":
        from chief_of_staff.agent.activity import log_activity, SUB_AGENT_SPAWN
        from chief_of_staff.agent.registry import get_registry

        registry = get_registry()
        config = registry.get(agent_name)
        if config and not config.permissions.get("can_create_agents"):
            return "Error: this agent does not have permission to create sub-agents."

        new_agent = registry.create_agent(
            name=args["name"],
            display_name=args["display_name"],
            system_prompt=args["system_prompt"],
            tools=args.get("tools", ["search_knowledge"]),
        )

        log_activity(
            agent_name=agent_name,
            action_type=SUB_AGENT_SPAWN,
            action_detail=f"Created sub-agent: {new_agent.name}",
            metadata={"sub_agent": new_agent.name, "tools": new_agent.tools},
        )
        return f"Sub-agent '{new_agent.display_name}' created with tools: {new_agent.tools}"

    if name == "delegate_task":
        from chief_of_staff.agent.activity import log_activity, DELEGATION
        from chief_of_staff.agent.core import get_agent_by_name
        from chief_of_staff.agent.delegation_context import enter_delegation, exit_delegation

        target_name = args["agent_name"]
        task = args["task"]
        current_depth, max_depth = _get_delegation_limit(agent_name)
        if current_depth >= max_depth:
            return (
                f"Error: max delegation depth reached ({current_depth}/{max_depth}). "
                "Complete this step directly or increase max_delegation_depth."
            )

        sub_agent = get_agent_by_name(target_name)
        if not sub_agent:
            return f"Error: sub-agent '{target_name}' not found."

        log_activity(
            agent_name=agent_name,
            action_type=DELEGATION,
            action_detail=f"Delegating to {target_name}",
            input_summary=task[:500],
        )

        token = enter_delegation()
        try:
            result = await sub_agent.respond(
                user_message=task,
                channel="delegation",
                user_id=agent_name,
            )
            return f"[{target_name} response]:\n{result}"
        except Exception as e:
            return f"Error delegating to {target_name}: {e}"
        finally:
            exit_delegation(token)

    if name == "spawn_sub_agent_task":
        from chief_of_staff.agent.activity import log_activity, SUB_AGENT_SPAWN
        from chief_of_staff.agent.request_context import get_request_context
        from chief_of_staff.config import settings
        from chief_of_staff.knowledge.database import create_sub_agent_run

        target_name = args["agent_name"]
        task = args["task"]
        announce_channel = args.get("announce_channel") or settings.subagent_announce_channel
        current_depth, max_depth = _get_delegation_limit(agent_name)
        if current_depth >= max_depth:
            return (
                f"Error: max delegation depth reached ({current_depth}/{max_depth}). "
                "Complete this step directly or increase max_delegation_depth."
            )

        ctx = get_request_context()
        run_id = str(uuid.uuid4())
        create_sub_agent_run(
            run_id=run_id,
            parent_agent=agent_name,
            child_agent=target_name,
            task=task,
            requester_channel=ctx.channel,
            requester_user_id=ctx.user_id,
            requester_session_id=ctx.session_id,
        )

        _ACTIVE_SUBAGENT_TASKS[run_id] = asyncio.create_task(
            _run_spawned_subagent(
                run_id=run_id,
                parent_agent=agent_name,
                child_agent=target_name,
                task=task,
                requester_channel=ctx.channel,
                announce_channel=announce_channel,
            )
        )

        log_activity(
            agent_name=agent_name,
            action_type=SUB_AGENT_SPAWN,
            action_detail=f"Spawned async sub-agent run: {run_id}",
            input_summary=task[:500],
            metadata={"run_id": run_id, "child_agent": target_name},
        )
        return f"Spawned sub-agent run `{run_id}` for `{target_name}`. Use list_sub_agent_tasks to track progress."

    if name == "list_sub_agent_tasks":
        from chief_of_staff.knowledge.database import list_sub_agent_runs

        status = args.get("status", "")
        limit = int(args.get("limit", 20))
        runs = list_sub_agent_runs(parent_agent=agent_name, status=status, limit=max(1, min(limit, 100)))
        if not runs:
            return "No sub-agent runs found."
        return json.dumps(runs, indent=2)

    if name == "cancel_sub_agent_task":
        from chief_of_staff.knowledge.database import get_sub_agent_run, mark_sub_agent_run_cancelled

        run_id = args["run_id"]
        task = _ACTIVE_SUBAGENT_TASKS.get(run_id)
        if task and not task.done():
            task.cancel()
            mark_sub_agent_run_cancelled(run_id, "Cancelled by parent agent")
            return f"Cancellation requested for run `{run_id}`."

        run = get_sub_agent_run(run_id)
        if not run:
            return f"Error: run `{run_id}` not found."
        if run.get("status") in ("completed", "failed", "cancelled"):
            return f"Run `{run_id}` is already `{run['status']}`."
        mark_sub_agent_run_cancelled(run_id, "Cancelled by parent agent")
        return f"Run `{run_id}` marked cancelled."

    raise ValueError(f"Unknown delegation tool: {name}")
