"""OpenClaw-style exec approvals store and request lifecycle."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
import time
import uuid
from typing import Any

from chief_of_staff.config import settings

_DEFAULT_POLICY = {
    "execEnabled": False,
    "requireApprovalByDefault": True,
    "allowCommandPrefixes": [],
    "denyCommandPrefixes": [],
}


def _now_epoch_ms() -> int:
    return int(time.time() * 1000)


class ExecApprovalsService:
    """Host-local persistent approvals state + runtime request decisions."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._policy: dict[str, Any] = copy.deepcopy(_DEFAULT_POLICY)
        self._requests: dict[str, dict[str, Any]] = {}
        self._load_locked()

    @property
    def path(self) -> str:
        return self._path

    def _load_locked(self) -> None:
        with self._lock:
            if not os.path.exists(self._path):
                return
            try:
                with open(self._path, encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception:
                return
            policy = payload.get("policy")
            if isinstance(policy, dict):
                self._policy = self._normalize_policy(policy)
            requests = payload.get("requests")
            if isinstance(requests, dict):
                self._requests = {
                    str(k): v
                    for k, v in requests.items()
                    if isinstance(k, str) and isinstance(v, dict)
                }

    def _save_locked(self) -> None:
        directory = os.path.dirname(self._path) or "."
        os.makedirs(directory, exist_ok=True)
        payload = {
            "version": 1,
            "updatedAt": _now_epoch_ms(),
            "policy": self._policy,
            "requests": self._requests,
        }
        fd, tmp = tempfile.mkstemp(prefix="exec-approvals-", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp, self._path)
        finally:
            try:
                os.remove(tmp)
            except FileNotFoundError:
                pass

    @staticmethod
    def _normalize_policy(policy: dict[str, Any]) -> dict[str, Any]:
        normalized = copy.deepcopy(_DEFAULT_POLICY)
        exec_enabled = policy.get("execEnabled")
        if isinstance(exec_enabled, bool):
            normalized["execEnabled"] = exec_enabled
        require = policy.get("requireApprovalByDefault")
        if isinstance(require, bool):
            normalized["requireApprovalByDefault"] = require
        allow = policy.get("allowCommandPrefixes")
        deny = policy.get("denyCommandPrefixes")
        if isinstance(allow, list):
            normalized["allowCommandPrefixes"] = [str(v).strip() for v in allow if str(v).strip()]
        if isinstance(deny, list):
            normalized["denyCommandPrefixes"] = [str(v).strip() for v in deny if str(v).strip()]
        return normalized

    @staticmethod
    def _prefix_matches(command: str, prefixes: list[str]) -> bool:
        command_trimmed = command.strip()
        if not command_trimmed:
            return False
        for prefix in prefixes:
            candidate = prefix.strip()
            if candidate and command_trimmed.startswith(candidate):
                return True
        return False

    def get_policy(self) -> dict[str, Any]:
        with self._lock:
            pending = sum(1 for req in self._requests.values() if req.get("status") == "pending")
            return {
                "path": self._path,
                "policy": copy.deepcopy(self._policy),
                "requestCount": len(self._requests),
                "pendingCount": pending,
            }

    def set_policy(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            update = payload.get("policy", payload)
            if not isinstance(update, dict):
                raise ValueError("policy must be an object")
            self._policy = self._normalize_policy(update)
            self._save_locked()
            return self.get_policy()

    def request_approval(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            request_payload = payload.get("request", payload)
            if not isinstance(request_payload, dict):
                raise ValueError("request must be an object")

            request_id = str(request_payload.get("requestId", "")).strip() or str(uuid.uuid4())
            now = _now_epoch_ms()
            record = {
                "requestId": request_id,
                "status": "pending",
                "createdAt": now,
                "updatedAt": now,
                "tool": str(request_payload.get("tool", "")).strip(),
                "command": str(request_payload.get("command", "")).strip(),
                "requestedBy": str(request_payload.get("requestedBy", "unknown")).strip() or "unknown",
                "reason": str(request_payload.get("reason", "")).strip(),
                "metadata": request_payload.get("metadata", {}),
            }
            self._requests[request_id] = record
            self._save_locked()
            self._cond.notify_all()
            return copy.deepcopy(record)

    def wait_decision(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_id = str(payload.get("requestId", "")).strip()
        if not request_id:
            raise ValueError("requestId is required")
        timeout_ms = payload.get("timeoutMs", 30000)
        if not isinstance(timeout_ms, int) or timeout_ms < 0:
            raise ValueError("timeoutMs must be a non-negative integer")

        with self._lock:
            record = self._requests.get(request_id)
            if not record:
                raise ValueError("requestId not found")

            if record.get("status") == "pending" and timeout_ms > 0:
                deadline = time.time() + (timeout_ms / 1000.0)
                while record.get("status") == "pending":
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        break
                    self._cond.wait(timeout=remaining)
                    record = self._requests.get(request_id, record)
            return copy.deepcopy(record)

    def resolve(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_id = str(payload.get("requestId", "")).strip()
        if not request_id:
            raise ValueError("requestId is required")
        decision = str(payload.get("decision", "")).strip().lower()
        if decision not in {"approved", "denied"}:
            raise ValueError("decision must be 'approved' or 'denied'")

        with self._lock:
            record = self._requests.get(request_id)
            if not record:
                raise ValueError("requestId not found")
            if record.get("status") != "pending":
                raise ValueError("request is already resolved")
            now = _now_epoch_ms()
            record["status"] = decision
            record["resolvedAt"] = now
            record["updatedAt"] = now
            record["decidedBy"] = str(payload.get("decidedBy", "operator")).strip() or "operator"
            record["decisionReason"] = str(payload.get("reason", "")).strip()
            self._save_locked()
            self._cond.notify_all()
            return copy.deepcopy(record)

    def authorize_command(self, command: str, requested_by: str = "unknown") -> dict[str, Any]:
        normalized_command = command.strip()
        if not normalized_command:
            raise ValueError("command is required")
        caller = requested_by.strip() or "unknown"
        with self._lock:
            if not self._policy.get("execEnabled", False):
                return {"status": "paused", "reason": "exec disabled by policy"}

            deny_prefixes = self._policy.get("denyCommandPrefixes", [])
            allow_prefixes = self._policy.get("allowCommandPrefixes", [])

            if self._prefix_matches(normalized_command, deny_prefixes):
                return {"status": "denied", "reason": "blocked by denyCommandPrefixes"}

            if self._prefix_matches(normalized_command, allow_prefixes):
                return {"status": "approved", "source": "allowCommandPrefixes"}

            # Reuse one-time explicit approval after operator resolve.
            for record in self._requests.values():
                if (
                    record.get("status") == "approved"
                    and not record.get("consumedAt")
                    and record.get("command", "") == normalized_command
                    and record.get("requestedBy", "") == caller
                ):
                    now = _now_epoch_ms()
                    record["consumedAt"] = now
                    record["updatedAt"] = now
                    self._save_locked()
                    return {"status": "approved", "source": "operator-approval", "requestId": record["requestId"]}

            if self._policy.get("requireApprovalByDefault", True):
                for record in self._requests.values():
                    if (
                        record.get("status") == "pending"
                        and record.get("command", "") == normalized_command
                        and record.get("requestedBy", "") == caller
                    ):
                        return {
                            "status": "needs_approval",
                            "requestId": record["requestId"],
                            "reason": "awaiting operator decision",
                        }

                pending = self.request_approval(
                    {
                        "request": {
                            "tool": "control.cmd",
                            "command": normalized_command,
                            "requestedBy": caller,
                            "reason": "command execution requested via control message",
                            "metadata": {"channel": "control"},
                        }
                    }
                )
                return {
                    "status": "needs_approval",
                    "requestId": pending["requestId"],
                    "reason": "approval required by policy",
                }

            return {"status": "approved", "source": "policy-open"}

    def invoke(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        if action == "exec.approvals.get":
            return self.get_policy()
        if action == "exec.approvals.set":
            return self.set_policy(args)
        if action == "exec.approval.request":
            return self.request_approval(args)
        if action == "exec.approval.waitDecision":
            return self.wait_decision(args)
        if action == "exec.approval.resolve":
            return self.resolve(args)
        raise ValueError(f"unsupported action: {action}")


_service: ExecApprovalsService | None = None
_service_lock = threading.Lock()


def get_exec_approvals_service() -> ExecApprovalsService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = ExecApprovalsService(path=settings.exec_approvals_path)
    return _service


def reset_exec_approvals_service_for_tests() -> None:
    global _service
    with _service_lock:
        _service = None
