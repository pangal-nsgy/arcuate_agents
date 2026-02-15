"""Communication skill — SMS, email, document drafting."""

from __future__ import annotations

import json
from typing import Any

SKILL_NAME = "communication"

TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "send_sms": {
        "name": "send_sms",
        "description": "Send a WhatsApp message or SMS to a phone number.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Phone number in E.164 format (+1...)"},
                "message": {"type": "string", "description": "The message to send"},
            },
            "required": ["to", "message"],
        },
    },
    "send_email": {
        "name": "send_email",
        "description": "Send an email on behalf of the Chief of Staff.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Email body (plain text)"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    "draft_document": {
        "name": "draft_document",
        "description": "Create a draft document (onboarding packet, proposal, summary, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Document title"},
                "content": {"type": "string", "description": "Full document content in markdown"},
                "doc_type": {
                    "type": "string",
                    "enum": ["onboarding_packet", "proposal", "summary", "memo", "other"],
                    "description": "Type of document",
                },
            },
            "required": ["title", "content", "doc_type"],
        },
    },
}


async def execute(name: str, args: dict[str, Any], agent_name: str) -> str:
    """Execute a communication tool. May raise — caller handles exceptions."""
    if name == "send_sms":
        from chief_of_staff.communication.sms import send_sms
        result = await send_sms(to=args["to"], body=args["message"])
        return f"SMS sent to {args['to']}: {result}"

    elif name == "send_email":
        from chief_of_staff.communication.email import send_email
        result = await send_email(to=args["to"], subject=args["subject"], body=args["body"])
        return f"Email sent to {args['to']}: {result}"

    elif name == "draft_document":
        return json.dumps({
            "status": "draft_created",
            "title": args["title"],
            "type": args["doc_type"],
            "content": args["content"],
        })

    else:
        raise ValueError(f"Unknown communication tool: {name}")
