"""Agent router — resolves which agent should handle a Discord message."""

from __future__ import annotations

import logging
import re
from typing import Any

from chief_of_staff.agent.registry import AgentConfig, get_registry

logger = logging.getLogger(__name__)

DEFAULT_AGENT = "chief_of_staff"


def resolve_agent(message_content: str, is_dm: bool = False) -> str:
    """Determine which agent should handle a message.

    Resolution order:
    1. Explicit @discord_name mention in message text (e.g., "hey onboarding")
    2. Specialist agent trigger words (checked before COS)
    3. Default: "chief_of_staff"
    """
    msg_lower = message_content.lower()
    registry = get_registry()
    agents = registry.list_agents()

    # Build a mapping of discord_name -> agent_name for all agents with discord_name set
    discord_names: dict[str, str] = {}
    specialist_agents: list[AgentConfig] = []

    for config in agents:
        if config.discord_name:
            discord_names[config.discord_name.lower()] = config.name
        # Specialists = any agent that isn't the default COS
        if config.name != DEFAULT_AGENT:
            specialist_agents.append(config)

    # 1. Check for explicit discord_name mention
    for discord_name, agent_name in discord_names.items():
        # Match as a standalone word
        if re.search(rf'\b{re.escape(discord_name)}\b', msg_lower):
            # Don't match the COS discord_name in this pass — that's the default anyway
            if agent_name != DEFAULT_AGENT:
                logger.info(f"Router: matched discord_name '{discord_name}' → {agent_name}")
                return agent_name

    # 2. Check specialist trigger words (before COS)
    for config in specialist_agents:
        for trigger in config.trigger_words:
            if trigger.lower() in msg_lower:
                logger.info(f"Router: trigger word '{trigger}' → {config.name}")
                return config.name

    # 3. Default to COS
    logger.debug(f"Router: no specialist match, defaulting to {DEFAULT_AGENT}")
    return DEFAULT_AGENT


def get_all_trigger_words() -> set[str]:
    """Get merged trigger words from ALL agents (for the _should_respond check)."""
    registry = get_registry()
    all_words: set[str] = set()
    for config in registry.list_agents():
        for word in config.trigger_words:
            all_words.add(word.lower())
        if config.discord_name:
            all_words.add(config.discord_name.lower())
    return all_words
