"""Memory skill — persistent memory storage and recall."""

from __future__ import annotations

from typing import Any

SKILL_NAME = "memory"

TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "remember": {
        "name": "remember",
        "description": "Store something in your persistent memory. Use for: key facts about people, decisions made, patterns noticed, things to follow up on. Memory persists across all conversations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "What to remember"},
                "category": {
                    "type": "string",
                    "enum": ["person", "decision", "pattern", "follow_up", "preference", "general"],
                    "description": "Category for the memory entry",
                },
            },
            "required": ["content", "category"],
        },
    },
    "recall_memory": {
        "name": "recall_memory",
        "description": "Search your persistent memory for previously stored information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for in memory"},
            },
            "required": ["query"],
        },
    },
}


async def execute(name: str, args: dict[str, Any], agent_name: str) -> str:
    """Execute a memory tool. May raise — caller handles exceptions."""
    if name == "remember":
        from chief_of_staff.agent.activity import log_activity, MEMORY_WRITE
        from chief_of_staff.agent.memory import append_memory_safe

        content = args["content"]
        category = args.get("category", "general")
        await append_memory_safe(agent_name, content, category)

        log_activity(
            agent_name=agent_name,
            action_type=MEMORY_WRITE,
            action_detail=f"[{category}] {content[:200]}",
        )
        return f"Remembered [{category}]: {content}"

    elif name == "recall_memory":
        from chief_of_staff.agent.activity import log_activity, MEMORY_READ
        from chief_of_staff.agent.memory import search_memory

        query = args["query"]
        results = search_memory(agent_name, query)

        log_activity(
            agent_name=agent_name,
            action_type=MEMORY_READ,
            action_detail=query,
            output_summary=f"{len(results)} entries found",
        )
        if not results:
            return "No matching memories found."
        return "\n---\n".join(results)

    else:
        raise ValueError(f"Unknown memory tool: {name}")
