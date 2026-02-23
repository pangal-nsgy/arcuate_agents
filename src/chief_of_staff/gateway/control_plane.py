"""Minimal control-plane action handlers for OpenClaw parity bridge."""

from __future__ import annotations

import threading
from typing import Any

from chief_of_staff.agent.rails import get_rails
from chief_of_staff.config import settings
from chief_of_staff.gateway.exec_approvals import get_exec_approvals_service
from chief_of_staff.gateway.usage_budget import get_usage_budget_service

_runtime_overrides: dict[str, Any] = {}
_lock = threading.RLock()


def _get_setting(key: str) -> Any:
    with _lock:
        if key in _runtime_overrides:
            return _runtime_overrides[key]
    if not hasattr(settings, key):
        raise ValueError(f"unknown config key: {key}")
    return getattr(settings, key)


def _config_snapshot() -> dict[str, Any]:
    keys = [
        "hooks_enabled",
        "hooks_default_session_key",
        "hooks_allow_request_session_key",
        "gateway_tools_deny",
        "gateway_tools_allow",
        "voice_exec_enabled",
        "voice_exec_dry_run",
        "bluebubbles_enabled",
        "bluebubbles_dm_policy",
        "bluebubbles_group_policy",
        "usage_run_budget_usd",
        "usage_session_budget_usd",
        "usage_day_budget_usd",
        "usage_default_action_cost_usd",
    ]
    return {key: _get_setting(key) for key in keys}


def invoke_control_action(action: str, args: dict[str, Any]) -> dict[str, Any]:
    if action == "health":
        return {"ok": True}

    if action == "status":
        rails = get_rails()
        approvals = get_exec_approvals_service().get_policy()
        usage = get_usage_budget_service().status(session_key="main", run_id="default")
        return {
            "ok": True,
            "rails": {
                "llm_enabled": rails.llm_enabled,
                "command_exec_enabled": approvals["policy"].get("execEnabled", False),
            },
            "approvals": {
                "pending": approvals["pendingCount"],
                "requireApprovalByDefault": approvals["policy"].get("requireApprovalByDefault", True),
            },
            "usage": usage,
        }

    if action == "config.get":
        key = str(args.get("key", "")).strip()
        if not key:
            return {"config": _config_snapshot()}
        return {"key": key, "value": _get_setting(key)}

    if action == "config.set":
        key = str(args.get("key", "")).strip()
        if not key:
            raise ValueError("key is required")
        if not hasattr(settings, key):
            raise ValueError(f"unknown config key: {key}")
        with _lock:
            _runtime_overrides[key] = args.get("value")
        return {"key": key, "value": _runtime_overrides[key]}

    if action in {"config.apply", "config.patch"}:
        updates = args.get("values", args.get("patch", args))
        if not isinstance(updates, dict):
            raise ValueError("values/patch must be an object")
        applied: dict[str, Any] = {}
        with _lock:
            for key, value in updates.items():
                key_name = str(key).strip()
                if not key_name:
                    continue
                if not hasattr(settings, key_name):
                    raise ValueError(f"unknown config key: {key_name}")
                _runtime_overrides[key_name] = value
                applied[key_name] = value
        return {"applied": applied}

    raise ValueError(f"unsupported control action: {action}")
