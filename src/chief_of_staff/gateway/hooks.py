"""OpenClaw-style hooks ingress endpoints (/hooks/wake, /hooks/agent)."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import inspect
import json
import os
import re
import uuid
from datetime import datetime, UTC
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request

from chief_of_staff.agent.activity import WEBHOOK_RECEIVED, log_activity
from chief_of_staff.agent.core import get_agent
from chief_of_staff.config import settings
from chief_of_staff.gateway.auth import extract_bearer_token

router = APIRouter(tags=["hooks"])

_active_hook_runs: dict[str, dict[str, str]] = {}
_transform_cache: dict[tuple[str, str], Callable[..., Any]] = {}
_BLOCKED_PATH_KEYS = {"__proto__", "prototype", "constructor"}


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


def _resolve_session_key(payload: dict[str, Any], allow_request_override: bool = False) -> str:
    requested = str(payload.get("sessionKey", "")).strip()
    if requested:
        if not (allow_request_override or settings.hooks_allow_request_session_key):
            raise HTTPException(status_code=400, detail="sessionKey override is not allowed")
        allowed = settings.hooks_allowed_session_key_prefixes
        if allowed and not any(requested.startswith(prefix) for prefix in allowed):
            raise HTTPException(status_code=400, detail="sessionKey prefix is not allowed")
        return requested
    return settings.hooks_default_session_key


def _normalize_hook_path(raw: str) -> str:
    return raw.strip().lstrip("/").rstrip("/")


def _parse_template_path(path_expr: str) -> list[str | int]:
    parts: list[str | int] = []
    for key, index in re.findall(r"([^.\[\]]+)|\[(\d+)\]", path_expr):
        if key:
            parts.append(key)
        elif index:
            parts.append(int(index))
    return parts


def _get_by_path(input_obj: Any, path_expr: str) -> Any:
    current = input_obj
    for part in _parse_template_path(path_expr):
        if isinstance(part, int):
            if not isinstance(current, list) or part < 0 or part >= len(current):
                return None
            current = current[part]
            continue
        if part in _BLOCKED_PATH_KEYS:
            return None
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


def _render_template(template: str, payload: dict[str, Any], request: Request, hook_path: str) -> str:
    if not template:
        return ""

    headers = {k.lower(): v for k, v in request.headers.items()}
    query = dict(request.query_params)

    def _resolve_expr(expr: str) -> Any:
        if expr == "path":
            return hook_path
        if expr == "now":
            return datetime.now(UTC).isoformat()
        if expr.startswith("headers."):
            return _get_by_path(headers, expr[len("headers.") :])
        if expr.startswith("query."):
            return _get_by_path(query, expr[len("query.") :])
        if expr.startswith("payload."):
            return _get_by_path(payload, expr[len("payload.") :])
        return _get_by_path(payload, expr)

    def _replace(match: re.Match[str]) -> str:
        expr = match.group(1).strip()
        value = _resolve_expr(expr)
        if value is None:
            return ""
        if isinstance(value, (str, int, float, bool)):
            return str(value)
        return json.dumps(value, separators=(",", ":"))

    return re.sub(r"\{\{\s*([^}]+)\s*\}\}", _replace, template)


def _render_optional(template: str | None, payload: dict[str, Any], request: Request, hook_path: str) -> str | None:
    if not template:
        return None
    rendered = _render_template(template, payload, request, hook_path).strip()
    return rendered if rendered else None


def _resolve_mapping(hook_name: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    hook_path = _normalize_hook_path(hook_name)
    source = str(payload.get("source", "")).strip()
    for idx, mapping in enumerate(settings.hooks_mappings):
        if not isinstance(mapping, dict):
            continue
        match = mapping.get("match", {})
        if match is None:
            match = {}
        if not isinstance(match, dict):
            continue
        path_match = _normalize_hook_path(str(match.get("path", "")).strip()) if match.get("path") else ""
        source_match = str(match.get("source", "")).strip()
        if path_match and path_match != hook_path:
            continue
        if source_match and source_match != source:
            continue
        resolved = dict(mapping)
        resolved["id"] = str(mapping.get("id", f"mapping-{idx + 1}")).strip() or f"mapping-{idx + 1}"
        return resolved
    return None


def _resolve_transform_fn(transform: dict[str, Any]) -> Callable[..., Any]:
    module_ref = str(transform.get("module", "")).strip()
    export_name = str(transform.get("export", "transform")).strip() or "transform"
    if not module_ref:
        raise HTTPException(status_code=400, detail="hook transform module path is required")

    root = os.path.realpath(settings.hooks_transforms_dir)
    module_path = module_ref if os.path.isabs(module_ref) else os.path.join(root, module_ref)
    module_path = os.path.realpath(module_path)
    if os.path.commonpath([root, module_path]) != root:
        raise HTTPException(status_code=400, detail="hook transform path escapes hooks_transforms_dir")
    if not os.path.exists(module_path):
        raise HTTPException(status_code=400, detail="hook transform module does not exist")

    cache_key = (module_path, export_name)
    if cache_key in _transform_cache:
        return _transform_cache[cache_key]

    unique_name = "hook_transform_" + hashlib.sha1(f"{module_path}:{export_name}".encode()).hexdigest()
    spec = importlib.util.spec_from_file_location(unique_name, module_path)
    if spec is None or spec.loader is None:
        raise HTTPException(status_code=400, detail="failed to load hook transform module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn = getattr(module, export_name, None)
    if not callable(fn):
        raise HTTPException(status_code=400, detail=f"hook transform export '{export_name}' is not callable")
    _transform_cache[cache_key] = fn
    return fn


async def _apply_mapping_transform(
    mapping: dict[str, Any],
    payload: dict[str, Any],
    request: Request,
    hook_path: str,
) -> dict[str, Any] | None:
    transform = mapping.get("transform")
    if not transform:
        return {}
    if not isinstance(transform, dict):
        raise HTTPException(status_code=400, detail="hook transform config must be an object")
    fn = _resolve_transform_fn(transform)
    ctx = {
        "payload": payload,
        "headers": {k.lower(): v for k, v in request.headers.items()},
        "url": str(request.url),
        "path": hook_path,
    }
    out = fn(ctx)
    if inspect.isawaitable(out):
        out = await out
    if out is None:
        return None
    if not isinstance(out, dict):
        raise HTTPException(status_code=400, detail="hook transform must return object or null")
    return out


def _build_action_from_mapping(
    mapping: dict[str, Any],
    payload: dict[str, Any],
    request: Request,
    hook_path: str,
    override: dict[str, Any],
) -> dict[str, Any]:
    action = str(mapping.get("action", "agent")).strip() or "agent"
    if action not in {"wake", "agent"}:
        raise HTTPException(status_code=400, detail="hook mapping action must be 'wake' or 'agent'")

    wake_mode = str(mapping.get("wakeMode", "now")).strip() or "now"
    if wake_mode not in {"now", "next-heartbeat"}:
        raise HTTPException(status_code=400, detail="hook mapping wakeMode must be 'now' or 'next-heartbeat'")

    if action == "wake":
        text = _render_template(str(mapping.get("textTemplate", "")), payload, request, hook_path)
        if "text" in override:
            text = str(override.get("text", "")).strip()
        mode = str(override.get("mode", wake_mode)).strip() or wake_mode
        return {"kind": "wake", "text": text, "mode": mode}

    message = _render_template(str(mapping.get("messageTemplate", "")), payload, request, hook_path)
    if "message" in override:
        message = str(override.get("message", "")).strip()
    name = _render_optional(mapping.get("name"), payload, request, hook_path) or "hook"
    if "name" in override:
        name = str(override.get("name", "hook")).strip() or "hook"
    session_key = _render_optional(mapping.get("sessionKey"), payload, request, hook_path)
    if "sessionKey" in override:
        session_key = str(override.get("sessionKey", "")).strip() or None
    mode = str(override.get("wakeMode", wake_mode)).strip() or wake_mode
    return {
        "kind": "agent",
        "message": message,
        "name": name,
        "sessionKey": session_key,
        "wakeMode": mode,
    }


def _handle_wake_payload(payload: dict[str, Any], action_detail: str = "hook.wake") -> dict[str, object]:
    text = str(payload.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    mode = str(payload.get("mode", "now")).strip()
    if mode not in {"now", "next-heartbeat"}:
        raise HTTPException(status_code=400, detail="mode must be 'now' or 'next-heartbeat'")

    log_activity(
        agent_name="chief_of_staff",
        action_type=WEBHOOK_RECEIVED,
        action_detail=action_detail,
        input_summary=text[:500],
        channel="hook",
        user_id="hook_wake",
    )
    return {"ok": True, "mode": mode}


def _handle_agent_payload(payload: dict[str, Any], action_detail: str = "hook.agent") -> dict[str, object]:
    message = str(payload.get("message", "")).strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    allow_request_override = bool(payload.get("_allow_mapping_session_key", False))
    session_key = _resolve_session_key(payload, allow_request_override=allow_request_override)
    run_id = str(uuid.uuid4())
    _active_hook_runs[run_id] = {"status": "running", "session_key": session_key}

    log_activity(
        agent_name="chief_of_staff",
        action_type=WEBHOOK_RECEIVED,
        action_detail=action_detail,
        input_summary=message[:500],
        channel="hook",
        user_id=str(payload.get("name", "hook")),
        session_id=session_key,
        metadata={"run_id": run_id},
    )

    asyncio.create_task(_run_agent_hook(run_id=run_id, payload=payload, session_key=session_key))
    return {"ok": True, "status": "accepted", "runId": run_id}


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
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON object body is required")
    return _handle_wake_payload(payload)


@router.post("/hooks/agent")
async def hooks_agent(request: Request) -> dict[str, object]:
    _require_hook_token(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON object body is required")
    return _handle_agent_payload(payload)


@router.post("/hooks/{hook_name}")
async def hooks_mapped(hook_name: str, request: Request) -> dict[str, object]:
    _require_hook_token(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON object body is required")

    hook_path = _normalize_hook_path(hook_name)
    mapping = _resolve_mapping(hook_path, payload)
    if not mapping:
        raise HTTPException(status_code=404, detail="hook mapping not found")

    override = await _apply_mapping_transform(mapping, payload, request, hook_path)
    if override is None:
        return {"ok": True, "mappingId": mapping["id"], "skipped": True}

    action = _build_action_from_mapping(mapping, payload, request, hook_path, override)
    if action["kind"] == "wake":
        result = _handle_wake_payload(
            {"text": action["text"], "mode": action["mode"]},
            action_detail=f"hook.mapped:{mapping['id']}:wake",
        )
        return {"ok": True, "mappingId": mapping["id"], "action": "wake", **result}

    mapped_payload: dict[str, Any] = {"message": action["message"], "name": action.get("name", "hook")}
    if action.get("sessionKey"):
        mapped_payload["sessionKey"] = action["sessionKey"]
        mapped_payload["_allow_mapping_session_key"] = True
    result = _handle_agent_payload(
        mapped_payload,
        action_detail=f"hook.mapped:{mapping['id']}:agent",
    )
    return {"ok": True, "mappingId": mapping["id"], "action": "agent", **result}


@router.get("/hooks/runs/{run_id}")
async def hooks_run_status(run_id: str, request: Request) -> dict[str, object]:
    _require_hook_token(request)
    record = _active_hook_runs.get(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="run not found")
    return {"ok": True, "runId": run_id, **record}
