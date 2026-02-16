"""Durable sub-agent runtime (spawn, cancel, recover)."""

from __future__ import annotations

import asyncio
import uuid

from chief_of_staff.agent.activity import ERROR, SUB_AGENT_SPAWN, log_activity
from chief_of_staff.agent.delegation_context import enter_delegation, exit_delegation
from chief_of_staff.agent.lanes import run_subagent_lane
from chief_of_staff.agent.core import get_agent_by_name
from chief_of_staff.config import settings
from chief_of_staff.knowledge.database import (
    create_sub_agent_run,
    list_sub_agent_runs,
    mark_sub_agent_run_cancelled,
    mark_sub_agent_run_completed,
    mark_sub_agent_run_failed,
    mark_sub_agent_run_running,
    get_sub_agent_run,
)

_ACTIVE_SUBAGENT_TASKS: dict[str, asyncio.Task] = {}


async def _announce_sub_agent_completion(
    run_id: str,
    child_agent: str,
    status: str,
    result_or_error: str,
    requester_channel: str,
    announce_channel: str,
) -> None:
    if requester_channel != "discord":
        return
    from chief_of_staff.communication.discord_bot import send_to_channel

    short = result_or_error[:1200]
    msg = (
        f"Sub-agent run `{run_id[:8]}` finished\n"
        f"- agent: `{child_agent}`\n"
        f"- status: `{status}`\n"
        f"- summary:\n{short}"
    )
    await send_to_channel(announce_channel, msg)


async def _run_subagent(
    run_id: str,
    parent_agent: str,
    child_agent: str,
    task: str,
    requester_channel: str,
    announce_channel: str,
) -> None:
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


def spawn_sub_agent_run(
    parent_agent: str,
    child_agent: str,
    task: str,
    requester_channel: str = "",
    requester_user_id: str = "",
    requester_session_id: str = "",
    announce_channel: str = "",
) -> str:
    """Create + schedule a durable sub-agent run."""
    run_id = str(uuid.uuid4())
    announce = announce_channel or settings.subagent_announce_channel

    create_sub_agent_run(
        run_id=run_id,
        parent_agent=parent_agent,
        child_agent=child_agent,
        task=task,
        requester_channel=requester_channel,
        requester_user_id=requester_user_id,
        requester_session_id=requester_session_id,
    )

    _ACTIVE_SUBAGENT_TASKS[run_id] = asyncio.create_task(
        _run_subagent(
            run_id=run_id,
            parent_agent=parent_agent,
            child_agent=child_agent,
            task=task,
            requester_channel=requester_channel,
            announce_channel=announce,
        )
    )
    return run_id


def cancel_sub_agent_run(run_id: str) -> str:
    """Cancel a sub-agent run by ID."""
    task = _ACTIVE_SUBAGENT_TASKS.get(run_id)
    if task and not task.done():
        task.cancel()
        mark_sub_agent_run_cancelled(run_id, "Cancelled by parent agent")
        return "cancel_requested"

    run = get_sub_agent_run(run_id)
    if not run:
        return "not_found"
    if run.get("status") in ("completed", "failed", "cancelled"):
        return run["status"]
    mark_sub_agent_run_cancelled(run_id, "Cancelled by parent agent")
    return "cancelled"


def list_active_run_ids() -> list[str]:
    return sorted([rid for rid, task in _ACTIVE_SUBAGENT_TASKS.items() if not task.done()])


def recover_pending_sub_agent_runs(limit: int = 100) -> int:
    """Recover queued/running sub-agent runs after a process restart."""
    recovered = 0
    candidates = list_sub_agent_runs(status="queued", limit=limit) + list_sub_agent_runs(status="running", limit=limit)
    for row in candidates:
        run_id = row["id"]
        if run_id in _ACTIVE_SUBAGENT_TASKS and not _ACTIVE_SUBAGENT_TASKS[run_id].done():
            continue
        parent_agent = row.get("parent_agent", "chief_of_staff")
        child_agent = row.get("child_agent", "")
        task = row.get("task", "")
        if not child_agent or not task:
            mark_sub_agent_run_failed(run_id, "Recovery failed: missing child_agent or task")
            continue
        announce = settings.subagent_announce_channel
        requester_channel = row.get("requester_channel", "")
        # Re-enqueue existing run ID by scheduling runner directly.
        _ACTIVE_SUBAGENT_TASKS[run_id] = asyncio.create_task(
            _run_subagent(
                run_id=run_id,
                parent_agent=parent_agent,
                child_agent=child_agent,
                task=task,
                requester_channel=requester_channel,
                announce_channel=announce,
            )
        )
        recovered += 1
    return recovered
