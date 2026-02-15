"""Meetings skill — send recording bots to meetings."""

from __future__ import annotations

from typing import Any

SKILL_NAME = "meetings"

TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "send_meeting_bot": {
        "name": "send_meeting_bot",
        "description": "Send a bot to join and record a Zoom/Google Meet/Teams meeting.",
        "input_schema": {
            "type": "object",
            "properties": {
                "meeting_url": {"type": "string", "description": "The meeting join URL"},
                "meeting_title": {"type": "string", "description": "Optional title for the meeting"},
            },
            "required": ["meeting_url"],
        },
    },
}


async def execute(name: str, args: dict[str, Any], agent_name: str) -> str:
    """Execute a meetings tool. May raise — caller handles exceptions."""
    if name == "send_meeting_bot":
        from chief_of_staff.ingestion.recall_bot import dispatch_bot
        result = await dispatch_bot(
            meeting_url=args["meeting_url"],
            meeting_title=args.get("meeting_title", ""),
        )
        bot_id = result.get("id", "unknown")
        return f"Meeting bot dispatched (ID: {bot_id}). Will transcribe automatically."

    else:
        raise ValueError(f"Unknown meetings tool: {name}")
