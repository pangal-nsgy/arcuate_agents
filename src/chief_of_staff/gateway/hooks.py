"""OpenClaw-style hooks ingress endpoints (/hooks/wake, /hooks/agent)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from chief_of_staff.agent.activity import WEBHOOK_RECEIVED, log_activity
from chief_of_staff.agent.core import get_agent
from chief_of_staff.config import settings
from chief_of_staff.gateway.auth import extract_bearer_token

router = APIRouter(tags=["hooks"])

_active_hook_runs: dict[str, dict[str, str]] = {}


def _hooks_enabled() -> bool:
    return settings.hooks_enabled and bool(settings.hooks_token)


def _require_hook_token(request: Request) -> None:
    if not _hooks_enabled():
        raise HTTPException(status_code=404, detail="Hooks are not enabled")

    # OpenClaw compatibility: reject query token, allow auth header or x-openclaw-token.
    if "token" in request.query_params:
        raise HTTPException(
            status_code=400,
            detail="Hook token must be provided via Authorization or X-OpenClaw-Token header",
        )

    token = extract_bearer_token(request) or request.headers.get("x-openclaw-token", "")
    if token != settings.hooks_token:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _resolve_session_key(payload: dict[str, Any]) -> str:
    requested = str(payload.get("sessionKey", "")).strip()
    if requested:
        if not settings.hooks_allow_request_session_key:
            raise HTTPException(status_code=400, detail="sessionKey override is not allowed")
        allowed = settings.hooks_allowed_session_key_prefixes
        if allowed and not any(requested.startswith(prefix) for prefix in allowed):
            raise HTTPException(status_code=400, detail="sessionKey prefix is not allowed")
        return requested
    return settings.hooks_default_session_key


async def _run_agent_hook(run_id: str, payload: dict[str, Any], session_key: str) -> None:
    try:
        message = str(payload["message"])
        agent = get_agent()
        user_id = str(payload.get("name", "hook"))
        response = await agent.respond(
            user_message=message,
            channel="hook",
            user_id=user_id,
            session_id=session_key,
        )
        _active_hook_runs[run_id]["status"] = "completed"
        _active_hook_runs[run_id]["result"] = response[:1000]
    except Exception as e:
        _active_hook_runs[run_id]["status"] = "failed"
        _active_hook_runs[run_id]["error"] = f"{type(e).__name__}: {e}"


@router.post("/hooks/wake")
async def hooks_wake(request: Request) -> dict[str, object]:
    _require_hook_token(request)
    payload = await request.json()

    text = str(payload.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    mode = str(payload.get("mode", "now")).strip()
    if mode not in {"now", "next-heartbeat"}:
        raise HTTPException(status_code=400, detail="mode must be 'now' or 'next-heartbeat'")

    log_activity(
        agent_name="chief_of_staff",
        action_type=WEBHOOK_RECEIVED,
        action_detail=f"hook.wake:{mode}",
        input_summary=text[:500],
        channel="hook",
        user_id="hook_wake",
    )

    # Current app has no heartbeat queue; we acknowledge intake deterministically.
    return {"ok": True, "mode": mode}


@router.post("/hooks/agent")
async def hooks_agent(request: Request) -> dict[str, object]:
    _require_hook_token(request)
    payload = await request.json()

    message = str(payload.get("message", "")).strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    session_key = _resolve_session_key(payload)
    run_id = str(uuid.uuid4())
    _active_hook_runs[run_id] = {"status": "running", "session_key": session_key}

    log_activity(
        agent_name="chief_of_staff",
        action_type=WEBHOOK_RECEIVED,
        action_detail="hook.agent",
        input_summary=message[:500],
        channel="hook",
        user_id=str(payload.get("name", "hook")),
        session_id=session_key,
        metadata={"run_id": run_id},
    )

    asyncio.create_task(_run_agent_hook(run_id=run_id, payload=payload, session_key=session_key))
    return {"ok": True, "status": "accepted", "runId": run_id}


@router.get("/hooks/runs/{run_id}")
async def hooks_run_status(run_id: str, request: Request) -> dict[str, object]:
    _require_hook_token(request)
    record = _active_hook_runs.get(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="run not found")
    return {"ok": True, "runId": run_id, **record}

