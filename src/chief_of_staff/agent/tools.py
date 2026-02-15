"""Tools facade — delegates to skill modules via SkillRegistry.

This module is the stable public API that core.py, dashboard/routes.py,
and tests import.  Actual tool definitions and implementations live in
the ``skills/`` sub-package.
"""

from __future__ import annotations

import logging
from typing import Any

from chief_of_staff.agent.skills import get_skill_registry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy proxy so ``from chief_of_staff.agent.tools import ALL_TOOL_DEFINITIONS``
# keeps working (dashboard/routes.py:16).
# ---------------------------------------------------------------------------


class _LazyToolDefs(dict):
    """Dict that populates itself from the SkillRegistry on first access."""

    _loaded: bool = False

    def _ensure(self) -> None:
        if not self._loaded:
            self.update(get_skill_registry().get_all_tool_definitions())
            self._loaded = True

    def __getitem__(self, key: str) -> Any:
        self._ensure()
        return super().__getitem__(key)

    def __contains__(self, key: object) -> bool:
        self._ensure()
        return super().__contains__(key)

    def __iter__(self):
        self._ensure()
        return super().__iter__()

    def __len__(self) -> int:
        self._ensure()
        return super().__len__()

    def keys(self):
        self._ensure()
        return super().keys()

    def values(self):
        self._ensure()
        return super().values()

    def items(self):
        self._ensure()
        return super().items()

    def get(self, key: str, default: Any = None) -> Any:
        self._ensure()
        return super().get(key, default)


ALL_TOOL_DEFINITIONS: dict[str, dict[str, Any]] = _LazyToolDefs()


# ---------------------------------------------------------------------------
# Public API (unchanged signatures)
# ---------------------------------------------------------------------------


def get_tool_definitions(tool_names: list[str]) -> list[dict[str, Any]]:
    """Get tool definitions for a specific set of tool names."""
    return get_skill_registry().get_tool_definitions(tool_names)


def get_server_tools(server_tools_config: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Get server tool definitions from config."""
    return server_tools_config if server_tools_config else []


async def execute_tool(name: str, args: dict[str, Any], agent_name: str = "chief_of_staff") -> str:
    """Execute a tool call and return the result as a string.

    Never raises — always returns a string (error message on failure).
    """
    try:
        return await get_skill_registry().execute_tool(name, args, agent_name)
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)[:500]
        logger.error(f"Tool '{name}' failed: {error_type}: {error_msg}", exc_info=True)
        from chief_of_staff.agent.activity import log_activity, ERROR
        log_activity(
            agent_name=agent_name,
            action_type=ERROR,
            action_detail=f"Tool '{name}' error: {error_type}: {error_msg}",
        )
        return f"Tool '{name}' encountered an error: {error_type}: {error_msg}. Try a different approach."
