"""Delegation skill — create sub-agents and delegate tasks."""

from __future__ import annotations

from typing import Any

SKILL_NAME = "delegation"

TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "create_sub_agent": {
        "name": "create_sub_agent",
        "description": "Create a new specialized sub-agent. Use when a recurring task needs a dedicated agent with a focused system prompt and specific tools.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Agent name (snake_case, e.g., lead_scorer)"},
                "display_name": {"type": "string", "description": "Human-readable name"},
                "system_prompt": {"type": "string", "description": "System prompt for the sub-agent"},
                "tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tools the sub-agent can use",
                },
            },
            "required": ["name", "display_name", "system_prompt"],
        },
    },
    "delegate_task": {
        "name": "delegate_task",
        "description": "Delegate a task to a sub-agent. The sub-agent runs autonomously and returns a result.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "Name of the sub-agent to delegate to"},
                "task": {"type": "string", "description": "The task to delegate"},
            },
            "required": ["agent_name", "task"],
        },
    },
}


async def execute(name: str, args: dict[str, Any], agent_name: str) -> str:
    """Execute a delegation tool. May raise — caller handles exceptions."""
    if name == "create_sub_agent":
        from chief_of_staff.agent.activity import log_activity, SUB_AGENT_SPAWN
        from chief_of_staff.agent.registry import get_registry

        registry = get_registry()
        config = registry.get(agent_name)
        if config and not config.permissions.get("can_create_agents"):
            return "Error: this agent does not have permission to create sub-agents."

        new_agent = registry.create_agent(
            name=args["name"],
            display_name=args["display_name"],
            system_prompt=args["system_prompt"],
            tools=args.get("tools", ["search_knowledge"]),
        )

        log_activity(
            agent_name=agent_name,
            action_type=SUB_AGENT_SPAWN,
            action_detail=f"Created sub-agent: {new_agent.name}",
            metadata={"sub_agent": new_agent.name, "tools": new_agent.tools},
        )
        return f"Sub-agent '{new_agent.display_name}' created with tools: {new_agent.tools}"

    elif name == "delegate_task":
        from chief_of_staff.agent.activity import log_activity, DELEGATION
        from chief_of_staff.agent.core import get_agent_by_name

        target_name = args["agent_name"]
        task = args["task"]

        sub_agent = get_agent_by_name(target_name)
        if not sub_agent:
            return f"Error: sub-agent '{target_name}' not found."

        log_activity(
            agent_name=agent_name,
            action_type=DELEGATION,
            action_detail=f"Delegating to {target_name}",
            input_summary=task[:500],
        )

        try:
            result = await sub_agent.respond(
                user_message=task,
                channel="delegation",
                user_id=agent_name,
            )
            return f"[{target_name} response]:\n{result}"
        except Exception as e:
            return f"Error delegating to {target_name}: {e}"

    else:
        raise ValueError(f"Unknown delegation tool: {name}")
