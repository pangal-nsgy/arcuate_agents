"""Process-local runtime rails and kill switches."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from chief_of_staff.config import settings


@dataclass
class RuntimeRails:
    llm_enabled: bool
    command_exec_enabled: bool


_lock = Lock()
_rails = RuntimeRails(
    llm_enabled=settings.llm_inbound_enabled,
    command_exec_enabled=settings.command_execution_enabled,
)


def get_rails() -> RuntimeRails:
    """Return a snapshot of runtime rail state."""
    with _lock:
        return RuntimeRails(
            llm_enabled=_rails.llm_enabled,
            command_exec_enabled=_rails.command_exec_enabled,
        )


def set_llm_enabled(enabled: bool) -> RuntimeRails:
    """Enable/disable LLM-backed inbound handling."""
    with _lock:
        _rails.llm_enabled = enabled
        return RuntimeRails(
            llm_enabled=_rails.llm_enabled,
            command_exec_enabled=_rails.command_exec_enabled,
        )


def set_command_exec_enabled(enabled: bool) -> RuntimeRails:
    """Enable/disable shell command execution."""
    with _lock:
        _rails.command_exec_enabled = enabled
        return RuntimeRails(
            llm_enabled=_rails.llm_enabled,
            command_exec_enabled=_rails.command_exec_enabled,
        )
