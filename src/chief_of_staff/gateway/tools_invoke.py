"""OpenClaw-style single-tool invoke HTTP endpoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from chief_of_staff.agent.tools import ALL_TOOL_DEFINITIONS, execute_tool
from chief_of_staff.config import settings
from chief_of_staff.gateway.auth import require_gateway_token

router = APIRouter(tags=["gateway-tools"])


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

    tool = str(payload.get("tool", "")).strip()
    if not tool:
        raise HTTPException(status_code=400, detail="tool is required")

    if tool not in ALL_TOOL_DEFINITIONS:
        raise HTTPException(status_code=404, detail="tool not available")

    if not _http_tool_allowed(tool):
        raise HTTPException(status_code=404, detail="tool not available")

    args = payload.get("args", {})
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise HTTPException(status_code=400, detail="args must be an object")

    action = payload.get("action")
    if action is not None and "action" not in args:
        args["action"] = action

    session_key = str(payload.get("sessionKey", "main"))
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
