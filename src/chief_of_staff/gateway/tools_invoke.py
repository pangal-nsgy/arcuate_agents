"""OpenClaw-style single-tool invoke HTTP endpoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from chief_of_staff.agent.tools import ALL_TOOL_DEFINITIONS, execute_tool
from chief_of_staff.config import settings
from chief_of_staff.gateway.auth import require_gateway_token
from chief_of_staff.gateway.control_plane import invoke_control_action
from chief_of_staff.gateway.exec_approvals import get_exec_approvals_service
from chief_of_staff.gateway.usage_budget import get_usage_budget_service

router = APIRouter(tags=["gateway-tools"])

_EXEC_APPROVAL_ACTIONS = {
    "exec.approvals.get",
    "exec.approvals.set",
    "exec.approval.request",
    "exec.approval.waitDecision",
    "exec.approval.resolve",
}
_USAGE_ACTIONS = {"usage.status", "usage.cost"}
_CONTROL_ACTIONS = {"health", "status", "config.get", "config.set", "config.apply", "config.patch"}


def _http_tool_allowed(tool_name: str) -> bool:
    deny = set(settings.gateway_tools_deny)
    allow = set(settings.gateway_tools_allow)

    # OpenClaw behavior: allow list can explicitly remove defaults from deny list.
    if tool_name in allow:
        return True
    if tool_name in deny:
        return False
    return True


@router.post("/tools/invoke")
async def tools_invoke(request: Request) -> dict[str, object]:
    require_gateway_token(request)
    payload = await request.json()

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON object body is required")

    args = payload.get("args", {})
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise HTTPException(status_code=400, detail="args must be an object")

    action = payload.get("action")
    action_name = str(action).strip() if action is not None else ""

    if action_name in _EXEC_APPROVAL_ACTIONS:
        try:
            result = get_exec_approvals_service().invoke(action_name, args)
            return {"ok": True, "result": result}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"unexpected exec approvals failure: {e}",
            ) from e

    if action_name in _USAGE_ACTIONS:
        service = get_usage_budget_service()
        session_key = str(payload.get("sessionKey", "main")).strip() or "main"
        run_id = str(payload.get("runId", "default")).strip() or "default"
        if action_name == "usage.status":
            return {"ok": True, "result": service.status(session_key=session_key, run_id=run_id)}
        return {"ok": True, "result": service.cost()}

    if action_name in _CONTROL_ACTIONS:
        try:
            return {"ok": True, "result": invoke_control_action(action_name, args)}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    tool = str(payload.get("tool", "")).strip()
    if not tool:
        raise HTTPException(status_code=400, detail="tool is required")

    if tool not in ALL_TOOL_DEFINITIONS:
        raise HTTPException(status_code=404, detail="tool not available")

    if not _http_tool_allowed(tool):
        raise HTTPException(status_code=404, detail="tool not available")

    if action is not None and "action" not in args:
        args["action"] = action

    session_key = str(payload.get("sessionKey", "main"))
    run_id = str(payload.get("runId", "default")).strip() or "default"
    cost_usd_raw = payload.get("costUsd", settings.usage_default_action_cost_usd)
    try:
        cost_usd = float(cost_usd_raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="costUsd must be numeric")

    budget = get_usage_budget_service().check_and_consume(
        session_key=session_key,
        run_id=run_id,
        cost_usd=cost_usd,
        reason="tools.invoke budget check",
    )
    if not budget.get("allowed"):
        raise HTTPException(
            status_code=429,
            detail=f"budget exceeded at {budget.get('scope')} scope",
        )

    agent_name = "chief_of_staff"
    if session_key.startswith("agent:"):
        # Future-friendly placeholder for agent-scoped execution.
        # Keep chief_of_staff as default for now.
        agent_name = "chief_of_staff"

    try:
        result = await execute_tool(tool, args, agent_name=agent_name)
        return {"ok": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"unexpected tool invoke failure: {e}") from e
