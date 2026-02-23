"""Deterministic phone command handling with strict guardrails."""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass

from chief_of_staff.agent.rails import (
    get_rails,
    set_command_exec_enabled,
    set_llm_enabled,
)
from chief_of_staff.config import settings


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
    return (
        "Runtime status:\n"
        f"- llm_enabled={rails.llm_enabled}\n"
        f"- command_exec_enabled={rails.command_exec_enabled}\n"
        f"- authorized_phone_count={len(allowed)}\n"
        f"- command_allowlist={allowlist}"
    )


def _execute_command(command: str) -> str:
    if not _is_allowed_command(command):
        return "Command blocked by allowlist."

    rails = get_rails()
    if not rails.command_exec_enabled:
        return (
            "Command execution is paused. Send '/resume exec' first, then retry."
        )

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
        rails = set_command_exec_enabled(False)
        return ControlResult(
            handled=True,
            response=(
                "Command execution paused.\n"
                f"llm_enabled={rails.llm_enabled}, command_exec_enabled={rails.command_exec_enabled}"
            ),
        )

    if message == "/resume exec":
        rails = set_command_exec_enabled(True)
        return ControlResult(
            handled=True,
            response=(
                "Command execution resumed.\n"
                f"llm_enabled={rails.llm_enabled}, command_exec_enabled={rails.command_exec_enabled}"
            ),
        )

    if message.startswith("cmd:"):
        command = message[len("cmd:") :].strip()
        if not command:
            return ControlResult(handled=True, response="No command provided after 'cmd:'.")
        return ControlResult(handled=True, response=_execute_command(command))

    return ControlResult(
        handled=True,
        response=(
            "Unknown control command. Use /status, /pause llm, /resume llm, "
            "/pause exec, /resume exec, or cmd: <command>."
        ),
    )

