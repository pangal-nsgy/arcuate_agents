"""Deterministic phone command handling with strict guardrails."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass

from chief_of_staff.agent.rails import (
    get_rails,
    set_llm_enabled,
)
from chief_of_staff.communication.bluebubbles_pairing import get_bluebubbles_pairing_store
from chief_of_staff.config import settings
from chief_of_staff.gateway.exec_approvals import get_exec_approvals_service
from chief_of_staff.gateway.usage_budget import get_usage_budget_service


@dataclass
class ControlResult:
    handled: bool
    response: str


def _authorized_phones() -> set[str]:
    configured = {p.strip() for p in settings.command_allowed_phones if p.strip()}
    if configured:
        return configured
    return {p.strip() for p in settings.founder_phone_numbers if p.strip()}


def _is_allowed_command(command: str) -> bool:
    try:
        parts = shlex.split(command)
    except ValueError:
        return False

    if not parts:
        return False

    for prefix in settings.command_allowed_prefixes:
        try:
            allowed_parts = shlex.split(prefix)
        except ValueError:
            continue
        if allowed_parts and parts[: len(allowed_parts)] == allowed_parts:
            return True
    return False


def _truncate(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def _status_text() -> str:
    rails = get_rails()
    allowed = _authorized_phones()
    allowlist = ", ".join(settings.command_allowed_prefixes)
    approvals = get_exec_approvals_service().get_policy()
    policy = approvals["policy"]
    return (
        "Runtime status:\n"
        f"- llm_enabled={rails.llm_enabled}\n"
        f"- command_exec_enabled={policy.get('execEnabled', False)}\n"
        f"- require_approval_by_default={policy.get('requireApprovalByDefault', True)}\n"
        f"- pending_approvals={approvals['pendingCount']}\n"
        f"- authorized_phone_count={len(allowed)}\n"
        f"- command_allowlist={allowlist}"
    )


def _execute_command(command: str, phone: str) -> str:
    if not _is_allowed_command(command):
        return "Command blocked by allowlist."

    authorization = get_exec_approvals_service().authorize_command(command, requested_by=phone)
    status = authorization.get("status")
    if status == "paused":
        return "Command execution is paused. Send '/resume exec' first, then retry."
    if status == "denied":
        return f"Command denied by approvals policy: {authorization.get('reason', 'denied')}."
    if status == "needs_approval":
        request_id = authorization.get("requestId", "")
        return (
            f"Approval required (id={request_id}). Resolve with exec.approval.resolve, then resend the same cmd."
        )

    budget = get_usage_budget_service().check_and_consume(
        session_key=phone,
        run_id="control-cmd",
        cost_usd=float(settings.usage_default_action_cost_usd),
        reason="control command execution",
    )
    if not budget.get("allowed"):
        return f"Budget exceeded at {budget.get('scope')} scope. Command blocked."

    try:
        completed = subprocess.run(
            shlex.split(command),
            capture_output=True,
            text=True,
            timeout=max(settings.command_timeout_seconds, 1),
            cwd=".",
        )
    except subprocess.TimeoutExpired:
        return f"Command timed out after {settings.command_timeout_seconds}s."
    except Exception as e:
        return f"Command failed before execution: {type(e).__name__}: {e}"

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    output = (
        f"exit_code={completed.returncode}\n"
        f"stdout:\n{stdout or '(empty)'}\n"
        f"stderr:\n{stderr or '(empty)'}"
    )
    return _truncate(output)


def handle_control_message(phone: str, body: str) -> ControlResult:
    """Handle deterministic inbound commands from phone messages."""
    message = (body or "").strip()
    if not message:
        return ControlResult(handled=False, response="")

    recognized = (
        message.startswith("/status")
        or message.startswith("/pause ")
        or message.startswith("/resume ")
        or message.startswith("/pair ")
        or message.startswith("cmd:")
    )
    if not recognized:
        return ControlResult(handled=False, response="")

    if phone not in _authorized_phones():
        return ControlResult(
            handled=True,
            response="Unauthorized number for control commands.",
        )

    if message == "/status":
        return ControlResult(handled=True, response=_status_text())

    if message == "/pause llm":
        rails = set_llm_enabled(False)
        return ControlResult(
            handled=True,
            response=(
                "LLM inbound paused.\n"
                f"llm_enabled={rails.llm_enabled}, command_exec_enabled={rails.command_exec_enabled}"
            ),
        )

    if message == "/resume llm":
        rails = set_llm_enabled(True)
        return ControlResult(
            handled=True,
            response=(
                "LLM inbound resumed.\n"
                f"llm_enabled={rails.llm_enabled}, command_exec_enabled={rails.command_exec_enabled}"
            ),
        )

    if message == "/pause exec":
        policy = get_exec_approvals_service().set_policy({"execEnabled": False})["policy"]
        return ControlResult(
            handled=True,
            response=(
                "Command execution paused.\n"
                f"llm_enabled={get_rails().llm_enabled}, command_exec_enabled={policy.get('execEnabled', False)}"
            ),
        )

    if message == "/resume exec":
        policy = get_exec_approvals_service().set_policy({"execEnabled": True})["policy"]
        return ControlResult(
            handled=True,
            response=(
                "Command execution resumed.\n"
                f"llm_enabled={get_rails().llm_enabled}, command_exec_enabled={policy.get('execEnabled', False)}"
            ),
        )

    if message.startswith("cmd:"):
        command = message[len("cmd:") :].strip()
        if not command:
            return ControlResult(handled=True, response="No command provided after 'cmd:'.")
        return ControlResult(handled=True, response=_execute_command(command, phone))

    if message == "/pair list":
        pending = get_bluebubbles_pairing_store().list_pending()
        if not pending:
            return ControlResult(handled=True, response="No pending BlueBubbles pairing requests.")
        lines = ["Pending BlueBubbles pairing requests:"]
        for item in pending[:20]:
            lines.append(f"- {item['code']} -> {item['sender']}")
        return ControlResult(handled=True, response="\n".join(lines))

    if message.startswith("/pair approve "):
        code = message[len("/pair approve ") :].strip()
        sender = get_bluebubbles_pairing_store().approve(code)
        if not sender:
            return ControlResult(handled=True, response=f"Pairing code not found: {code}")
        return ControlResult(handled=True, response=f"Approved BlueBubbles pairing for {sender}.")

    if message.startswith("/pair deny "):
        code = message[len("/pair deny ") :].strip()
        sender = get_bluebubbles_pairing_store().deny(code)
        if not sender:
            return ControlResult(handled=True, response=f"Pairing code not found: {code}")
        return ControlResult(handled=True, response=f"Denied BlueBubbles pairing for {sender}.")

    return ControlResult(
        handled=True,
        response=(
            "Unknown control command. Use /status, /pause llm, /resume llm, "
            "/pause exec, /resume exec, /pair list, /pair approve <code>, /pair deny <code>, "
            "or cmd: <command>."
        ),
    )
