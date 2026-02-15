#!/usr/bin/env python3
"""AI Conflict Resolver — Opus 4.6 resolves merge conflicts automatically.

Standalone script (no app imports). Runs in GitHub Actions when the
Guardian's merge step hits conflicts.

Reads conflict markers from files, sends both sides + project context to
Opus 4.6, writes the resolved files, and stages them.

Usage:
  python scripts/resolve_conflicts.py
  # Exit code 0 = all conflicts resolved, 1 = resolution failed, 2 = error

Environment:
  ANTHROPIC_API_KEY  — required
"""

from __future__ import annotations

import json
import os
import re
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


def get_conflicted_files() -> list[str]:
    """Get list of files with merge conflicts."""
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]


def read_file(path: str) -> str | None:
    full_path = REPO_ROOT / path
    if full_path.exists():
        try:
            return full_path.read_text()
        except Exception:
            return None
    return None


def get_project_context() -> str:
    claude_md = REPO_ROOT / "CLAUDE.md"
    if claude_md.exists():
        content = claude_md.read_text()
        if len(content) > 3000:
            content = content[:3000] + "\n... (truncated)"
        return content
    return "No CLAUDE.md found."


def build_resolution_prompt(
    file_path: str,
    conflicted_content: str,
    project_context: str,
) -> str:
    return f"""You are a senior engineer resolving a git merge conflict in an AI agent system (Python/FastAPI).

## Project Context
{project_context}

## Conflicted File: {file_path}

The file below contains git conflict markers (<<<<<<< / ======= / >>>>>>>).
The section between <<<<<<< and ======= is from the **dev branch** (new feature/fix).
The section between ======= and >>>>>>> is from the **deploy branch** (current production).

```
{conflicted_content[:12000]}
```

## Your Task

Resolve the conflict by producing the COMPLETE file content with:
1. Both sides' changes merged intelligently (not just picking one side)
2. No conflict markers remaining
3. Valid Python/YAML syntax
4. No duplicate imports, functions, or definitions
5. All new functionality from dev preserved
6. No regressions to existing production behavior

## Response Format

Respond with ONLY a JSON object:
{{
  "resolved_content": "the complete file content with conflicts resolved",
  "explanation": "brief explanation of how you resolved each conflict"
}}

IMPORTANT: The resolved_content must be the COMPLETE file — not a diff or partial snippet."""


def call_claude(prompt: str, api_key: str) -> dict:
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
            "max_tokens": 8192,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=180,
    )

    if resp.status_code != 200:
        print(f"[ERROR] Claude API returned {resp.status_code}: {resp.text[:500]}")
        return {}

    response_text = resp.json()["content"][0]["text"].strip()

    # Strip markdown fences if present
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1]
    if response_text.endswith("```"):
        response_text = response_text.rsplit("```", 1)[0]
    response_text = response_text.strip()

    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        print(f"[ERROR] Could not parse Claude response as JSON")
        print(f"  Response: {response_text[:500]}")
        return {}


def validate_resolution(file_path: str, content: str) -> bool:
    """Basic validation that the resolution is syntactically valid."""
    # Check no conflict markers remain
    if "<<<<<<" in content or "=======" in content or ">>>>>>>" in content:
        # Be more precise — ======= can appear in markdown/strings
        lines = content.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("<<<<<<<") or stripped.startswith(">>>>>>>"):
                print(f"  [FAIL] Conflict markers still present in {file_path}")
                return False

    # Python syntax check
    if file_path.endswith(".py"):
        import ast
        try:
            ast.parse(content, filename=file_path)
        except SyntaxError as e:
            print(f"  [FAIL] Python syntax error in {file_path}: {e}")
            return False

    # YAML syntax check
    if file_path.endswith((".yaml", ".yml")):
        import yaml
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as e:
            print(f"  [FAIL] YAML syntax error in {file_path}: {e}")
            return False

    return True


def main() -> int:
    print("=" * 60)
    print("AI Conflict Resolver — Opus 4.6")
    print("=" * 60)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[ERROR] ANTHROPIC_API_KEY not set")
        return 2

    conflicted = get_conflicted_files()
    if not conflicted:
        print("No conflicted files found.")
        return 0

    print(f"\nConflicted files ({len(conflicted)}):")
    for f in conflicted:
        print(f"  - {f}")

    project_context = get_project_context()
    resolved_count = 0
    failed_files = []

    for file_path in conflicted:
        print(f"\n{'─' * 40}")
        print(f"Resolving: {file_path}")

        content = read_file(file_path)
        if content is None:
            print(f"  [SKIP] Could not read {file_path}")
            failed_files.append(file_path)
            continue

        prompt = build_resolution_prompt(file_path, content, project_context)
        result = call_claude(prompt, api_key)

        if not result or "resolved_content" not in result:
            print(f"  [FAIL] No resolution returned for {file_path}")
            failed_files.append(file_path)
            continue

        resolved = result["resolved_content"]
        explanation = result.get("explanation", "No explanation")

        # Validate
        if not validate_resolution(file_path, resolved):
            failed_files.append(file_path)
            continue

        # Write resolved file
        full_path = REPO_ROOT / file_path
        full_path.write_text(resolved)

        # Stage the resolved file
        subprocess.run(
            ["git", "add", file_path],
            cwd=str(REPO_ROOT), check=True,
        )

        print(f"  [OK] Resolved: {explanation[:200]}")
        resolved_count += 1

    print(f"\n{'=' * 60}")
    print(f"Resolved: {resolved_count}/{len(conflicted)} files")

    if failed_files:
        print(f"FAILED: {', '.join(failed_files)}")
        # Write output for GitHub Actions
        github_output = os.environ.get("GITHUB_OUTPUT")
        if github_output:
            with open(github_output, "a") as f:
                f.write(f"resolved=false\n")
                f.write(f"failed_files={','.join(failed_files)}\n")
        return 1

    # Write output for GitHub Actions
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"resolved=true\n")
            f.write(f"resolved_count={resolved_count}\n")

    print("All conflicts resolved successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
