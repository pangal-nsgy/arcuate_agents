"""AI-powered merge conflict detection and auto-resolution.

Called by the GitHub Action when high-risk files are modified.
Uses Claude Opus 4.6 via httpx (no SDK needed in CI).
Posts results to Discord via webhook.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
MERGE_RESOLVER_MODEL = "claude-opus-4-6"

# Files that warrant AI conflict analysis
HIGH_RISK_PATTERNS = [
    "agents/",
    "src/chief_of_staff/agent/tools.py",
    "src/chief_of_staff/main.py",
    "architecture_changelog.yaml",
]


@dataclass
class ConflictResult:
    """Result of AI conflict analysis for a single file."""

    file_path: str
    has_conflict: bool
    severity: str  # "none", "low", "medium", "high"
    description: str
    suggested_fix: str
    auto_fixable: bool
    resolved_content: str | None = None


def is_high_risk(file_path: str) -> bool:
    """Check if a file path matches high-risk patterns."""
    for pattern in HIGH_RISK_PATTERNS:
        if file_path.startswith(pattern) or file_path == pattern.rstrip("/"):
            return True
    return False


def _build_analysis_prompt(file_path: str, diff: str, file_content: str) -> str:
    """Build a file-type-specific analysis prompt."""
    if file_path.endswith(".yaml") or file_path.endswith(".yml"):
        context = (
            "This is a YAML configuration file for an AI agent system. "
            "Check for: duplicate keys, incompatible field changes, "
            "tool names that don't exist, invalid YAML structure."
        )
    elif file_path == "src/chief_of_staff/agent/tools.py":
        context = (
            "This is the tool registry and dispatcher. "
            "Check for: duplicate tool names in ALL_TOOL_DEFINITIONS, "
            "tool definitions without handlers, handlers without definitions, "
            "broken imports, incompatible function signatures."
        )
    elif file_path == "architecture_changelog.yaml":
        context = (
            "This is a changelog of architecture decisions. "
            "Check for: duplicate entries, missing required fields (date, author, category, title), "
            "invalid categories."
        )
    else:
        context = (
            "Check for semantic conflicts: incompatible changes, "
            "broken imports, duplicate definitions, type mismatches."
        )

    return f"""Analyze this code change for semantic conflicts. Two developers are working on the same codebase and this file was just modified.

**File**: {file_path}

**Context**: {context}

**Diff**:
```
{diff}
```

**Current file content after the push**:
```
{file_content}
```

Respond with ONLY a JSON object (no markdown, no explanation):
{{
  "has_conflict": true/false,
  "severity": "none" | "low" | "medium" | "high",
  "description": "What the conflict is (or 'No conflicts detected')",
  "suggested_fix": "How to fix it (or 'N/A')",
  "auto_fixable": true/false
}}

- "has_conflict": true only if there's an actual semantic problem (not just a style difference)
- "auto_fixable": true only if you can deterministically fix it without human judgment
- Be conservative: flag real issues, not stylistic preferences"""


def _build_fix_prompt(file_path: str, file_content: str, conflict_desc: str) -> str:
    """Build a prompt to generate the fixed file content."""
    return f"""Fix the following conflict in this file. Return ONLY the complete corrected file content with no markdown fences or explanation.

**File**: {file_path}
**Conflict**: {conflict_desc}

**Current content**:
```
{file_content}
```

Return the complete fixed file. Do not add comments about what you changed."""


async def analyze_file(
    file_path: str,
    diff: str,
    file_content: str,
    anthropic_api_key: str,
) -> ConflictResult:
    """Analyze a single file for semantic conflicts using Claude."""
    prompt = _build_analysis_prompt(file_path, diff, file_content)

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": MERGE_RESOLVER_MODEL,
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )

        if resp.status_code != 200:
            logger.error(f"Claude API error {resp.status_code}: {resp.text[:300]}")
            return ConflictResult(
                file_path=file_path,
                has_conflict=False,
                severity="none",
                description=f"Analysis failed: API error {resp.status_code}",
                suggested_fix="N/A",
                auto_fixable=False,
            )

        response_text = resp.json()["content"][0]["text"]
        # Strip markdown fences if present
        response_text = response_text.strip()
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[1]
        if response_text.endswith("```"):
            response_text = response_text.rsplit("```", 1)[0]
        response_text = response_text.strip()

        result = json.loads(response_text)

        return ConflictResult(
            file_path=file_path,
            has_conflict=result.get("has_conflict", False),
            severity=result.get("severity", "none"),
            description=result.get("description", "No description"),
            suggested_fix=result.get("suggested_fix", "N/A"),
            auto_fixable=result.get("auto_fixable", False),
        )

    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Failed to parse Claude response for {file_path}: {e}")
        return ConflictResult(
            file_path=file_path,
            has_conflict=False,
            severity="none",
            description=f"Analysis failed: could not parse response ({e})",
            suggested_fix="N/A",
            auto_fixable=False,
        )
    except httpx.TimeoutException:
        return ConflictResult(
            file_path=file_path,
            has_conflict=False,
            severity="none",
            description="Analysis failed: API timeout",
            suggested_fix="N/A",
            auto_fixable=False,
        )


async def generate_fix(
    file_path: str,
    file_content: str,
    conflict_desc: str,
    anthropic_api_key: str,
) -> str | None:
    """Generate a fixed version of a file using Claude. Returns new content or None."""
    prompt = _build_fix_prompt(file_path, file_content, conflict_desc)

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": MERGE_RESOLVER_MODEL,
                    "max_tokens": 8192,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )

        if resp.status_code != 200:
            logger.error(f"Fix generation failed: {resp.status_code}")
            return None

        return resp.json()["content"][0]["text"]

    except Exception as e:
        logger.error(f"Fix generation error: {e}")
        return None


async def post_to_discord(
    webhook_url: str,
    title: str,
    description: str,
    color: int,
    fields: list[dict[str, str]] | None = None,
) -> bool:
    """Post an embed to a Discord webhook. Returns True on success."""
    embed: dict[str, Any] = {
        "title": title,
        "description": description[:4096],
        "color": color,
    }
    if fields:
        embed["fields"] = fields[:25]  # Discord limit

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                webhook_url,
                json={"embeds": [embed]},
            )
        return resp.status_code in (200, 204)
    except Exception as e:
        logger.error(f"Discord webhook failed: {e}")
        return False


# Discord embed colors
COLOR_BLUE = 0x3498DB    # Push received
COLOR_GREEN = 0x2ECC71   # All checks passed
COLOR_YELLOW = 0xF1C40F  # Auto-resolved
COLOR_RED = 0xE74C3C     # Needs manual review
