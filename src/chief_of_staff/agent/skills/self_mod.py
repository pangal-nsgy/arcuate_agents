"""Self-modification skill — update instructions, system prompt, triage config."""

from __future__ import annotations

from typing import Any

SKILL_NAME = "self_mod"

TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "update_own_instructions": {
        "name": "update_own_instructions",
        "description": "Update your own standing instructions. Use this when you learn recurring patterns, preferences, or rules that should persist across conversations. These instructions are injected into your system prompt on every message.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "remove", "replace_all"],
                    "description": "add: append a new instruction. remove: remove by index. replace_all: replace all instructions.",
                },
                "instruction": {"type": "string", "description": "The instruction to add (for 'add' action)"},
                "index": {"type": "integer", "description": "Index to remove (for 'remove' action, 0-based)"},
                "instructions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Full list of instructions (for 'replace_all' action)",
                },
            },
            "required": ["action"],
        },
    },
    "update_system_prompt": {
        "name": "update_system_prompt",
        "description": "Rewrite your own base system prompt. Use this when a founder asks you to fundamentally change your personality, role, tone, or core behavior. This replaces the entire system prompt — write the complete new version, not a diff. Your standing instructions and memory are injected separately and are NOT affected.",
        "input_schema": {
            "type": "object",
            "properties": {
                "new_prompt": {
                    "type": "string",
                    "description": "The complete new system prompt to replace the current one.",
                },
                "reason": {
                    "type": "string",
                    "description": "Brief explanation of why you're changing the prompt (logged for audit).",
                },
            },
            "required": ["new_prompt", "reason"],
        },
    },
    "update_triage_config": {
        "name": "update_triage_config",
        "description": "Update your Discord listener behavior — when you respond to messages. You can change the triage prompt (the LLM prompt that decides YES/NO on whether to respond) and/or the trigger words (keywords that always make you respond without LLM triage). Changes take effect on the next Discord message.",
        "input_schema": {
            "type": "object",
            "properties": {
                "triage_prompt": {
                    "type": "string",
                    "description": "New triage prompt template. Use {channel}, {author}, {message}, {context} as placeholders. Must instruct the LLM to respond YES or NO only.",
                },
                "trigger_words": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of keywords/phrases that always trigger a response (case-insensitive, no LLM needed). E.g. ['angie', 'chief of staff'].",
                },
            },
        },
    },
}


async def execute(name: str, args: dict[str, Any], agent_name: str) -> str:
    """Execute a self-modification tool. May raise — caller handles exceptions."""
    if name == "update_own_instructions":
        from chief_of_staff.agent.activity import log_activity, CONFIG_UPDATE
        from chief_of_staff.agent.registry import get_registry

        registry = get_registry()
        config = registry.get(agent_name)
        if not config:
            return f"Error: agent '{agent_name}' not found."
        if not config.permissions.get("can_self_modify"):
            return "Error: this agent does not have permission to self-modify."

        action = args["action"]
        if action == "add":
            instruction = args.get("instruction", "")
            if not instruction:
                return "Error: 'instruction' required for add action."
            config.standing_instructions.append(instruction)
        elif action == "remove":
            idx = args.get("index", -1)
            if 0 <= idx < len(config.standing_instructions):
                config.standing_instructions.pop(idx)
            else:
                return f"Error: invalid index {idx}. Current instructions count: {len(config.standing_instructions)}"
        elif action == "replace_all":
            config.standing_instructions = args.get("instructions", [])
        else:
            return f"Error: unknown action '{action}'"

        registry.update_agent_instructions(agent_name, config.standing_instructions)

        log_activity(
            agent_name=agent_name,
            action_type=CONFIG_UPDATE,
            action_detail=f"update_own_instructions: {action}",
            input_summary=str(args)[:500],
            output_summary=str(config.standing_instructions)[:500],
        )
        return f"Instructions updated. Current standing instructions ({len(config.standing_instructions)}):\n" + \
               "\n".join(f"  {i}. {inst}" for i, inst in enumerate(config.standing_instructions))

    elif name == "update_system_prompt":
        from chief_of_staff.agent.activity import log_activity, CONFIG_UPDATE
        from chief_of_staff.agent.registry import get_registry

        registry = get_registry()
        config = registry.get(agent_name)
        if not config:
            return f"Error: agent '{agent_name}' not found."
        if not config.permissions.get("can_self_modify"):
            return "Error: this agent does not have permission to self-modify."

        new_prompt = args.get("new_prompt", "")
        reason = args.get("reason", "no reason given")
        if not new_prompt.strip():
            return "Error: new_prompt cannot be empty."

        old_length = len(config.system_prompt)
        registry.update_agent_system_prompt(agent_name, new_prompt)

        log_activity(
            agent_name=agent_name,
            action_type=CONFIG_UPDATE,
            action_detail=f"update_system_prompt: {reason}",
            input_summary=f"old_length={old_length}, new_length={len(new_prompt)}",
            output_summary=new_prompt[:500],
        )
        return f"System prompt rewritten ({old_length} → {len(new_prompt)} chars). Reason: {reason}. Takes effect on next message."

    elif name == "update_triage_config":
        from chief_of_staff.agent.activity import log_activity, CONFIG_UPDATE
        from chief_of_staff.agent.registry import get_registry

        registry = get_registry()
        config = registry.get(agent_name)
        if not config:
            return f"Error: agent '{agent_name}' not found."
        if not config.permissions.get("can_self_modify"):
            return "Error: this agent does not have permission to self-modify."

        new_triage = args.get("triage_prompt")
        new_triggers = args.get("trigger_words")

        if new_triage is None and new_triggers is None:
            return "Error: provide at least one of triage_prompt or trigger_words."

        changes = []
        if new_triage is not None:
            changes.append(f"triage_prompt updated ({len(new_triage)} chars)")
        if new_triggers is not None:
            changes.append(f"trigger_words updated ({len(new_triggers)} words: {new_triggers})")

        registry.update_agent_triage_config(agent_name, new_triage, new_triggers)

        log_activity(
            agent_name=agent_name,
            action_type=CONFIG_UPDATE,
            action_detail=f"update_triage_config: {', '.join(changes)}",
            input_summary=str(args)[:500],
            output_summary=str(changes),
        )
        return f"Triage config updated: {', '.join(changes)}. Takes effect on next Discord message."

    else:
        raise ValueError(f"Unknown self_mod tool: {name}")
