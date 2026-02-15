"""Knowledge skill — search company knowledge base, emails, meetings."""

from __future__ import annotations

import json
from typing import Any

SKILL_NAME = "knowledge"

TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "search_knowledge": {
        "name": "search_knowledge",
        "description": "Search the company knowledge base (emails, docs, call transcripts, meeting notes).",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"},
                "source_filter": {
                    "type": "string",
                    "enum": ["gmail", "gdocs", "elevenlabs", "meeting"],
                    "description": "Optionally filter by source type",
                },
            },
            "required": ["query"],
        },
    },
    "list_recent_emails": {
        "name": "list_recent_emails",
        "description": "List recent emails from the knowledge base.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term for emails"},
                "limit": {"type": "integer", "description": "Max results (default 10)"},
            },
            "required": ["query"],
        },
    },
    "search_meetings": {
        "name": "search_meetings",
        "description": "Search meeting transcripts (Zoom, Recall.ai bot transcripts).",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query for meetings"},
                "limit": {"type": "integer", "description": "Max results (default 10)"},
            },
            "required": ["query"],
        },
    },
}


async def execute(name: str, args: dict[str, Any], agent_name: str) -> str:
    """Execute a knowledge tool. May raise — caller handles exceptions."""
    from chief_of_staff.knowledge import store as knowledge_store

    if name == "search_knowledge":
        from chief_of_staff.agent.activity import log_activity, KNOWLEDGE_SEARCH
        log_activity(
            agent_name=agent_name,
            action_type=KNOWLEDGE_SEARCH,
            action_detail=args["query"],
            input_summary=args.get("source_filter", "all"),
        )
        results = knowledge_store.search(
            query=args["query"],
            n_results=args.get("limit", 10),
            source_filter=args.get("source_filter"),
        )
        if not results:
            return "No results found."
        formatted = []
        for r in results:
            src = r["metadata"].get("source", "?")
            title = r["metadata"].get("title", "untitled")
            formatted.append(f"[{src}: {title}]\n{r['text'][:500]}")
        return "\n---\n".join(formatted)

    elif name == "list_recent_emails":
        from chief_of_staff.knowledge.database import search_documents
        docs = search_documents(query=args["query"], source="gmail", limit=args.get("limit", 10))
        if not docs:
            return "No emails found matching that query."
        return json.dumps(docs, indent=2, default=str)

    elif name == "search_meetings":
        results = knowledge_store.search(
            query=args["query"],
            n_results=args.get("limit", 10),
            source_filter="meeting",
        )
        if not results:
            return "No meeting transcripts found."
        formatted = []
        for r in results:
            title = r["metadata"].get("title", "untitled")
            platform = r["metadata"].get("platform", "unknown")
            formatted.append(f"[{platform}: {title}]\n{r['text'][:500]}")
        return "\n---\n".join(formatted)

    else:
        raise ValueError(f"Unknown knowledge tool: {name}")
