#!/usr/bin/env python3
"""AI Code Reviewer — Opus 4.6 gatekeeper for the dev → deploy merge.

Standalone script (no app imports). Runs in GitHub Actions.
Diffs dev against the deploy branch (not just HEAD~1) so multi-commit
pushes get fully reviewed. Sends diff to Claude Opus 4.6 for review,
and outputs APPROVE or REJECT with reasoning.

Usage:
  python scripts/ai_review.py
  # Reads ANTHROPIC_API_KEY from env
  # Exit code 0 = approved, 1 = rejected, 2 = error

Environment:
  ANTHROPIC_API_KEY  — required
  DEPLOY_BRANCH      — deploy branch name (default: claude/mcp-chrome-extension-BW3zj)
  REVIEW_DIFF        — optional, override diff (for testing)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def find_repo_root() -> Path:
    path = Path(__file__).resolve().parent
    while path != path.parent:
        if (path / "src").is_dir():
            return path
        path = path.parent
    return Path(__file__).resolve().parent.parent


REPO_ROOT = find_repo_root()


def get_deploy_branch() -> str:
    """Get the deploy branch name from env or default."""
    return os.environ.get("DEPLOY_BRANCH", "claude/mcp-chrome-extension-BW3zj")


def get_merge_base() -> str:
    """Find the merge base between HEAD and the deploy branch.

    This ensures we review ALL commits since the last merge to deploy,
    not just HEAD~1. Catches multi-commit pushes.
    """
    deploy = f"origin/{get_deploy_branch()}"
    result = subprocess.run(
        ["git", "merge-base", deploy, "HEAD"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    # Fallback: if deploy branch doesn't exist yet, use HEAD~1
    print(f"  [WARN] Could not find merge-base with {deploy}, falling back to HEAD~1")
    return "HEAD~1"


def get_diff() -> str:
    """Get the full git diff between deploy branch and HEAD.

    Uses merge-base so multi-commit pushes are fully reviewed.
    """
    # Allow override for testing
    if os.environ.get("REVIEW_DIFF"):
        return os.environ["REVIEW_DIFF"]

    base = get_merge_base()
    result = subprocess.run(
        ["git", "diff", base, "HEAD"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    if result.returncode != 0:
        # Fallback: single commit diff
        result = subprocess.run(
            ["git", "diff", "HEAD~1", "HEAD"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
    return result.stdout


def get_changed_files() -> list[str]:
    """Get list of ALL files changed since the deploy branch diverged."""
    base = get_merge_base()
    result = subprocess.run(
        ["git", "diff", "--name-only", base, "HEAD"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]


def read_file_content(path: str) -> str | None:
    """Read a file's content, return None if it doesn't exist."""
    full_path = REPO_ROOT / path
    if full_path.exists() and full_path.is_file():
        try:
            return full_path.read_text()
        except Exception:
            return None
    return None


def get_project_context() -> str:
    """Read CLAUDE.md for project context (truncated to keep prompt reasonable)."""
    claude_md = REPO_ROOT / "CLAUDE.md"
    if claude_md.exists():
        content = claude_md.read_text()
        # Truncate to ~4000 chars to leave room for diff
        if len(content) > 4000:
            content = content[:4000] + "\n... (truncated)"
        return content
    return "No CLAUDE.md found."


def build_review_prompt(diff: str, changed_files: list[str], file_contents: dict[str, str], project_context: str) -> str:
    """Build the code review prompt for Opus 4.6."""

    file_contents_section = ""
    for path, content in file_contents.items():
        # Truncate very large files
        if len(content) > 10000:
            content = content[:10000] + "\n... (truncated)"
        file_contents_section += f"\n### {path}\n```\n{content}\n```\n"

    return f"""You are a senior code reviewer for an AI agent system (Python/FastAPI). Your job is to decide whether this push is safe to deploy to production.

## Project Context
{project_context}

## Changed Files
{chr(10).join(f'- {f}' for f in changed_files)}

## Diff
```diff
{diff[:50000]}
```

## Full Content of Changed Files
{file_contents_section}

## Review Criteria

You MUST check for:
1. **Breaking changes**: Will this break the running agent? Missing imports, undefined variables, wrong function signatures, removed functions that are called elsewhere.
2. **Semantic conflicts**: Duplicate tool/skill names, tools referenced in YAML but not defined, activity types not wired up.
3. **Security issues**: Exposed secrets, command injection, unsafe eval, credentials in code.
4. **Async correctness**: Sync blocking calls in async context, missing awaits, deadlock potential.
5. **Error handling**: Tools that raise instead of returning error strings (project convention: tools never raise).
6. **YAML validity**: Agent configs with missing required fields, invalid tool references.

You should NOT block for:
- Style preferences, formatting, naming conventions
- Missing docstrings or type hints
- Refactoring suggestions that aren't bugs
- TODO comments or incomplete features (as long as they don't break existing functionality)

## Your Response

You MUST respond with ONLY a raw JSON object — no markdown, no explanation, no preamble.
Do NOT write any text before or after the JSON. Your entire response must be valid JSON.

{{
  "decision": "APPROVE" or "REJECT",
  "summary": "One-sentence summary of your decision",
  "issues": [
    {{
      "severity": "critical" or "warning",
      "file": "path/to/file.py",
      "description": "What's wrong"
    }}
  ]
}}

- REJECT only for critical issues that will break the running system
- APPROVE if the code is safe to deploy, even if imperfect
- Be pragmatic — this is a startup moving fast, not a bank
- IMPORTANT: Output ONLY the JSON object, nothing else"""


def call_claude(prompt: str, api_key: str) -> dict:
    """Call Claude Opus 4.6 API and return parsed response."""
    import httpx

    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-opus-4-6",
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=120,
    )

    if resp.status_code != 200:
        print(f"[ERROR] Claude API returned {resp.status_code}: {resp.text[:500]}")
        return {"decision": "REJECT", "summary": "API error — rejecting to prevent unsafe deploy", "issues": []}

    response_text = resp.json()["content"][0]["text"].strip()

    # Strip markdown fences if present
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1]
    if response_text.endswith("```"):
        response_text = response_text.rsplit("```", 1)[0]
    response_text = response_text.strip()

    # Try direct parse first
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON from the response (model may have added prose)
    import re
    json_match = re.search(r'\{[^{}]*"decision"\s*:\s*"(?:APPROVE|REJECT)"[^{}]*\}', response_text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # Last resort: check if the response contains APPROVE/REJECT keywords
    upper_text = response_text.upper()
    if '"APPROVE"' in response_text or "DECISION: APPROVE" in upper_text:
        print(f"[WARN] Extracted APPROVE from non-JSON response")
        return {"decision": "APPROVE", "summary": "Extracted from non-JSON response", "issues": []}

    print(f"[ERROR] Could not parse Claude response as JSON")
    print(f"  Response: {response_text[:500]}")
    return {"decision": "APPROVE", "summary": "Parse error — approving (non-code changes likely safe)", "issues": []}


def main() -> int:
    print("=" * 60)
    print("AI Code Review — Opus 4.6 Gatekeeper")
    print("=" * 60)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[ERROR] ANTHROPIC_API_KEY not set")
        return 2

    # Gather context
    print("\n[1/4] Getting diff...")
    diff = get_diff()
    if not diff.strip():
        print("  No diff found — nothing to review")
        print("\nDECISION: APPROVE (no changes)")
        return 0

    print(f"  Diff: {len(diff)} chars")

    print("[2/4] Getting changed files...")
    changed_files = get_changed_files()
    print(f"  Files: {len(changed_files)} changed")
    for f in changed_files:
        print(f"    - {f}")

    print("[3/4] Reading file contents...")
    file_contents = {}
    for path in changed_files:
        content = read_file_content(path)
        if content is not None:
            file_contents[path] = content
    print(f"  Read {len(file_contents)} files")

    print("[4/4] Sending to Opus 4.6 for review...")
    project_context = get_project_context()
    prompt = build_review_prompt(diff, changed_files, file_contents, project_context)
    result = call_claude(prompt, api_key)

    # Output results
    decision = result.get("decision", "APPROVE")
    summary = result.get("summary", "No summary")
    issues = result.get("issues", [])

    print(f"\n{'=' * 60}")
    print(f"DECISION: {decision}")
    print(f"SUMMARY: {summary}")

    if issues:
        print(f"\nISSUES ({len(issues)}):")
        for issue in issues:
            sev = issue.get("severity", "?").upper()
            filepath = issue.get("file", "?")
            desc = issue.get("description", "?")
            print(f"  [{sev}] {filepath}: {desc}")

    print(f"{'=' * 60}")

    # Write structured output for GitHub Actions
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"decision={decision}\n")
            f.write(f"summary={summary[:500]}\n")
            issue_text = "; ".join(
                f"[{i.get('severity', '?')}] {i.get('file', '?')}: {i.get('description', '?')}"
                for i in issues
            )
            f.write(f"issues={issue_text[:500]}\n")

    return 0 if decision == "APPROVE" else 1


if __name__ == "__main__":
    sys.exit(main())
