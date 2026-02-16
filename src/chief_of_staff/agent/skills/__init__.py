"""Skill registry — modular tool collections that agents can load."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

def _discover_skill_modules() -> list[str]:
    """Discover skill modules from files in this package."""
    skills_dir = Path(__file__).resolve().parent
    modules = []
    for path in sorted(skills_dir.glob("*.py")):
        if path.name == "__init__.py" or path.name.startswith("_"):
            continue
        modules.append(path.stem)
    return modules


class SkillRegistry:
    """Central registry mapping skill names and tool names to their modules."""

    def __init__(self) -> None:
        self._skills: dict[str, Any] = {}       # skill_name -> module
        self._tool_map: dict[str, Any] = {}      # tool_name -> module
        self._tool_defs: dict[str, dict] = {}    # tool_name -> definition dict
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        for mod_name in _discover_skill_modules():
            try:
                module = importlib.import_module(f".{mod_name}", package=__package__)
                self.register(module)
            except Exception as e:
                logger.error(f"Failed to load skill module '{mod_name}': {e}")
        self._loaded = True

    def reload(self) -> None:
        """Reload all skill modules from disk."""
        self._skills.clear()
        self._tool_map.clear()
        self._tool_defs.clear()
        self._loaded = False
        self._ensure_loaded()

    def register(self, module: Any) -> None:
        """Register a skill module (must have SKILL_NAME, TOOL_DEFINITIONS, execute)."""
        skill_name = module.SKILL_NAME
        self._skills[skill_name] = module
        for tool_name, tool_def in module.TOOL_DEFINITIONS.items():
            self._tool_map[tool_name] = module
            self._tool_defs[tool_name] = tool_def
        logger.debug(f"Registered skill '{skill_name}' with tools: {list(module.TOOL_DEFINITIONS)}")

    def get_tool_definitions(self, tool_names: list[str]) -> list[dict[str, Any]]:
        """Get tool definition dicts for a list of tool names."""
        self._ensure_loaded()
        return [self._tool_defs[n] for n in tool_names if n in self._tool_defs]

    def get_all_tool_definitions(self) -> dict[str, dict[str, Any]]:
        """Get all tool definitions as a dict (tool_name -> definition)."""
        self._ensure_loaded()
        return dict(self._tool_defs)

    def resolve_skills(self, refs: list[str]) -> list[str]:
        """Resolve a mixed list of skill names and tool names into a flat, deduplicated tool list.

        Example: ["knowledge", "send_email"] -> ["search_knowledge", "list_recent_emails", "search_meetings", "send_email"]
        """
        self._ensure_loaded()
        result: list[str] = []
        seen: set[str] = set()
        for ref in refs:
            if ref in self._skills:
                # It's a skill name — expand to all its tools
                for tool_name in self._skills[ref].TOOL_DEFINITIONS:
                    if tool_name not in seen:
                        result.append(tool_name)
                        seen.add(tool_name)
            elif ref in self._tool_map:
                # It's a single tool name
                if ref not in seen:
                    result.append(ref)
                    seen.add(ref)
            else:
                logger.warning(f"Unknown skill or tool: '{ref}'")
        return result

    async def execute_tool(self, name: str, args: dict[str, Any], agent_name: str) -> str:
        """Dispatch a tool call to the appropriate skill module."""
        self._ensure_loaded()
        module = self._tool_map.get(name)
        if module is None:
            # If a new skill file was created at runtime, try one reload pass.
            self.reload()
            module = self._tool_map.get(name)
        if module is None:
            return f"Unknown tool: {name}"
        return await module.execute(name, args, agent_name)


# Singleton
_registry: SkillRegistry | None = None


def get_skill_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry
