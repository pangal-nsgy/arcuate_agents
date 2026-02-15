"""Persistent memory per agent — file-based (Markdown) for readability and git tracking."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Base directory for agent memory files
MEMORY_DIR = Path(os.environ.get("AGENT_MEMORY_DIR", "./agent_memory"))

# Per-agent write locks for concurrent safety
_locks: dict[str, asyncio.Lock] = {}


def _get_lock(agent_name: str) -> asyncio.Lock:
    """Get or create a per-agent asyncio lock."""
    if agent_name not in _locks:
        _locks[agent_name] = asyncio.Lock()
    return _locks[agent_name]


def _memory_path(agent_name: str) -> Path:
    """Get the memory file path for an agent."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    return MEMORY_DIR / f"{agent_name}.md"


def read_memory(agent_name: str) -> str:
    """Read an agent's persistent memory. Returns empty string if none exists."""
    path = _memory_path(agent_name)
    if path.exists():
        return path.read_text()
    return ""


def append_memory(agent_name: str, content: str, category: str = "general") -> str:
    """Append a new entry to an agent's memory (sync version). Returns the updated memory."""
    path = _memory_path(agent_name)
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    entry = f"\n## [{category}] {timestamp}\n{content}\n"

    if path.exists():
        existing = path.read_text()
    else:
        existing = f"# Agent Memory: {agent_name}\n\nPersistent learnings and context accumulated by this agent.\n"

    updated = existing + entry
    path.write_text(updated)
    logger.info(f"Memory appended for {agent_name}: [{category}] {content[:100]}...")
    return updated


async def append_memory_safe(agent_name: str, content: str, category: str = "general") -> str:
    """Async-safe memory append with per-agent locking."""
    lock = _get_lock(agent_name)
    async with lock:
        return append_memory(agent_name, content, category)


def search_memory(agent_name: str, query: str) -> list[str]:
    """Simple keyword search across an agent's memory entries."""
    memory = read_memory(agent_name)
    if not memory:
        return []

    query_lower = query.lower()
    results = []
    current_entry = []
    for line in memory.split("\n"):
        if line.startswith("## ["):
            if current_entry and any(query_lower in l.lower() for l in current_entry):
                results.append("\n".join(current_entry))
            current_entry = [line]
        else:
            current_entry.append(line)

    # Check last entry
    if current_entry and any(query_lower in l.lower() for l in current_entry):
        results.append("\n".join(current_entry))

    return results


def clear_memory(agent_name: str) -> None:
    """Clear an agent's memory (use with caution)."""
    path = _memory_path(agent_name)
    if path.exists():
        path.write_text(f"# Agent Memory: {agent_name}\n\nMemory cleared on {datetime.utcnow().isoformat()}\n")
        logger.info(f"Memory cleared for {agent_name}")
