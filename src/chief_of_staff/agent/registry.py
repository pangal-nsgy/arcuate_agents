"""Agent registry — loads agent definitions from YAML config files."""

from __future__ import annotations

import logging
import os
from fnmatch import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

AGENTS_DIR = Path(os.environ.get("AGENTS_DIR", "./agents"))


@dataclass
class AgentConfig:
    """Configuration for a single agent, loaded from YAML."""

    name: str
    display_name: str = ""
    model: str = "claude-sonnet-4-5-20250929"
    max_tokens: int = 4096
    max_iterations: int = 10
    system_prompt: str = ""
    tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    discord_name: str = ""
    server_tools: list[dict[str, Any]] = field(default_factory=list)
    permissions: dict[str, Any] = field(default_factory=dict)
    standing_instructions: list[str] = field(default_factory=list)
    triage_prompt: str = ""
    trigger_words: list[str] = field(default_factory=list)
    request_timeout: int = 120
    planner_model: str = "claude-haiku-4-5-20251001"
    overflow_model: str = "gpt-4.1"
    overflow_iterations: int = 10
    tool_policy: dict[str, list[str]] = field(default_factory=dict)

    @staticmethod
    def _matches_any_pattern(tool_name: str, patterns: list[str]) -> bool:
        name = tool_name.lower()
        for pattern in patterns:
            if fnmatch(name, pattern.lower()):
                return True
        return False

    def _apply_tool_policy(self, tool_names: list[str]) -> list[str]:
        """Apply allow/deny tool policy (deny precedence, wildcard support)."""
        policy = self.tool_policy or {}
        allow = [str(v) for v in policy.get("allow", []) if str(v).strip()]
        deny = [str(v) for v in policy.get("deny", []) if str(v).strip()]

        filtered: list[str] = []
        for name in tool_names:
            # Deny wins (including deny-all wildcard).
            if "*" in deny or self._matches_any_pattern(name, deny):
                continue
            # Empty allow means allow-by-default (unless denied above).
            if allow and "*" not in allow and not self._matches_any_pattern(name, allow):
                continue
            filtered.append(name)
        return filtered

    def get_resolved_tools(self) -> list[str]:
        """Resolve skills + explicit tools into a flat tool name list."""
        if not self.skills:
            return self._apply_tool_policy(self.tools)  # backward compatible
        from chief_of_staff.agent.skills import get_skill_registry
        resolved = get_skill_registry().resolve_skills(self.skills)
        for t in self.tools:
            if t not in resolved:
                resolved.append(t)
        return self._apply_tool_policy(resolved)

    @classmethod
    def from_yaml(cls, path: Path) -> AgentConfig:
        """Load agent config from a YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(
            name=data.get("name", path.stem),
            display_name=data.get("display_name", data.get("name", path.stem)),
            model=data.get("model", "claude-sonnet-4-5-20250929"),
            max_tokens=data.get("max_tokens", 4096),
            max_iterations=data.get("max_iterations", 10),
            system_prompt=data.get("system_prompt", ""),
            tools=data.get("tools", []),
            skills=data.get("skills", []),
            discord_name=data.get("discord_name", ""),
            server_tools=data.get("server_tools", []),
            permissions=data.get("permissions", {}),
            standing_instructions=data.get("standing_instructions", []),
            triage_prompt=data.get("triage_prompt", ""),
            trigger_words=data.get("trigger_words", []),
            request_timeout=data.get("request_timeout", 120),
            planner_model=data.get("planner_model", "claude-haiku-4-5-20251001"),
            overflow_model=data.get("overflow_model", "gpt-4.1"),
            overflow_iterations=data.get("overflow_iterations", 10),
            tool_policy=data.get("tool_policy", {}),
        )

    def to_yaml(self, path: Path) -> None:
        """Save agent config to a YAML file."""
        data = {
            "name": self.name,
            "display_name": self.display_name,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "max_iterations": self.max_iterations,
            "system_prompt": self.system_prompt,
            "tools": self.tools,
            "skills": self.skills,
            "discord_name": self.discord_name,
            "server_tools": self.server_tools,
            "permissions": self.permissions,
            "standing_instructions": self.standing_instructions,
            "triage_prompt": self.triage_prompt,
            "trigger_words": self.trigger_words,
            "request_timeout": self.request_timeout,
            "planner_model": self.planner_model,
            "overflow_model": self.overflow_model,
            "overflow_iterations": self.overflow_iterations,
            "tool_policy": self.tool_policy,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        logger.info(f"Agent config saved: {path}")

    def build_system_prompt(self) -> str:
        """Build the full system prompt including standing instructions and memory."""
        prompt = self.system_prompt

        if self.standing_instructions:
            prompt += "\n\n--- STANDING INSTRUCTIONS (self-set) ---\n"
            for i, instruction in enumerate(self.standing_instructions, 1):
                prompt += f"{i}. {instruction}\n"
            prompt += "--- END STANDING INSTRUCTIONS ---"

        # Inject persistent memory
        from chief_of_staff.agent.memory import read_memory
        memory = read_memory(self.name)
        if memory:
            prompt += f"\n\n--- YOUR PERSISTENT MEMORY ---\n{memory[:4000]}\n--- END MEMORY ---"

        return prompt


class AgentRegistry:
    """Manages all agent configurations."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentConfig] = {}
        self._load_all()

    def _load_all(self) -> None:
        """Load all agent configs from the agents directory."""
        if not AGENTS_DIR.exists():
            logger.warning(f"Agents directory not found: {AGENTS_DIR}")
            return

        for path in AGENTS_DIR.glob("*.yaml"):
            try:
                config = AgentConfig.from_yaml(path)
                self._agents[config.name] = config
                logger.info(f"Loaded agent config: {config.name} ({config.display_name})")
            except Exception as e:
                logger.error(f"Failed to load agent config {path}: {e}")

    def get(self, name: str) -> AgentConfig | None:
        """Get an agent config by name. Re-reads from disk for freshness."""
        path = AGENTS_DIR / f"{name}.yaml"
        if path.exists():
            try:
                config = AgentConfig.from_yaml(path)
                self._agents[name] = config
                return config
            except Exception as e:
                logger.error(f"Failed to reload agent config {name}: {e}")
        return self._agents.get(name)

    def list_agents(self) -> list[AgentConfig]:
        """List all registered agents."""
        self._load_all()
        return list(self._agents.values())

    def create_agent(
        self,
        name: str,
        display_name: str,
        system_prompt: str,
        tools: list[str] | None = None,
        model: str = "claude-sonnet-4-5-20250929",
    ) -> AgentConfig:
        """Create a new agent and save its config."""
        config = AgentConfig(
            name=name,
            display_name=display_name,
            model=model,
            system_prompt=system_prompt,
            tools=tools or ["search_knowledge"],
            permissions={"can_self_modify": False, "can_create_agents": False, "can_send_external": False},
        )
        path = AGENTS_DIR / f"{name}.yaml"
        config.to_yaml(path)
        self._agents[name] = config
        logger.info(f"Created new agent: {name}")
        return config

    def update_agent_instructions(self, name: str, new_instructions: list[str]) -> AgentConfig | None:
        """Update an agent's standing instructions and save."""
        config = self.get(name)
        if not config:
            return None
        config.standing_instructions = new_instructions
        path = AGENTS_DIR / f"{name}.yaml"
        config.to_yaml(path)
        return config

    def update_agent_system_prompt(self, name: str, new_prompt: str) -> AgentConfig | None:
        """Update an agent's base system prompt and save."""
        config = self.get(name)
        if not config:
            return None
        config.system_prompt = new_prompt
        path = AGENTS_DIR / f"{name}.yaml"
        config.to_yaml(path)
        return config

    def update_agent_triage_config(
        self, name: str, triage_prompt: str | None = None, trigger_words: list[str] | None = None
    ) -> AgentConfig | None:
        """Update an agent's triage prompt and/or trigger words and save."""
        config = self.get(name)
        if not config:
            return None
        if triage_prompt is not None:
            config.triage_prompt = triage_prompt
        if trigger_words is not None:
            config.trigger_words = trigger_words
        path = AGENTS_DIR / f"{name}.yaml"
        config.to_yaml(path)
        return config


# Singleton
_registry: AgentRegistry | None = None


def get_registry() -> AgentRegistry:
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry
