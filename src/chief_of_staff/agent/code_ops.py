"""Code self-modification via GitHub REST API.

Allows the agent to read, edit, and deploy its own source code.
Uses the GitHub Contents API and Git Data API (blobs, trees, commits, refs)
so it works from Railway (no git CLI needed).
"""

from __future__ import annotations

import ast
import base64
import logging
from typing import Any

import httpx
import yaml

from chief_of_staff.config import settings

logger = logging.getLogger(__name__)

# In-memory staging area: {file_path: content_string}
_staged_files: dict[str, str] = {}

# Paths that must never be read or written
BLOCKED_PATTERNS = [
    ".env",
    "credentials.json",
    "token.json",
    ".git/",
    "venv/",
    "chroma_data/",
]
BLOCKED_EXTENSIONS = [".db"]


def _api_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _api_base() -> str:
    return f"https://api.github.com/repos/{settings.github_repo}"


def is_path_blocked(path: str) -> str | None:
    """Return a reason string if the path is blocked, else None."""
    normalized = path.lstrip("/")
    for pattern in BLOCKED_PATTERNS:
        if normalized == pattern.rstrip("/") or normalized.startswith(pattern):
            return f"Blocked path: '{path}' matches blocked pattern '{pattern}'"
    for ext in BLOCKED_EXTENSIONS:
        if normalized.endswith(ext):
            return f"Blocked path: '{path}' has blocked extension '{ext}'"
    return None


def validate_syntax(path: str, content: str) -> str | None:
    """Validate file syntax. Returns error string or None if valid."""
    if path.endswith(".py"):
        try:
            ast.parse(content, filename=path)
        except SyntaxError as e:
            return f"Python syntax error in {path} line {e.lineno}: {e.msg}"
    elif path.endswith((".yaml", ".yml")):
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as e:
            return f"YAML syntax error in {path}: {e}"
    return None


async def read_file_from_github(path: str) -> dict[str, Any]:
    """Read a file from the GitHub repo.

    Returns {"content": str, "sha": str} on success,
    or {"error": str} on failure.
    """
    if not settings.github_token:
        return {"error": "GITHUB_TOKEN not configured."}

    blocked = is_path_blocked(path)
    if blocked:
        return {"error": blocked}

    url = f"{_api_base()}/contents/{path.lstrip('/')}"
    params = {"ref": settings.github_branch}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_api_headers(), params=params)

    if resp.status_code == 404:
        return {"error": f"File not found: {path}"}
    if resp.status_code != 200:
        return {"error": f"GitHub API error {resp.status_code}: {resp.text[:300]}"}

    data = resp.json()
    # GitHub returns a list for directories
    if isinstance(data, list):
        files = [item["name"] for item in data[:50]]
        return {"error": f"'{path}' is a directory, not a file. Contents: {', '.join(files)}"}
    if data.get("type") != "file":
        return {"error": f"'{path}' is a {data.get('type', 'unknown')}, not a file."}

    content = base64.b64decode(data["content"]).decode("utf-8")
    return {"content": content, "sha": data["sha"]}


def stage_file(path: str, content: str) -> str:
    """Validate syntax and add a file to the staging area.

    Returns a success message or an error string.
    """
    blocked = is_path_blocked(path)
    if blocked:
        return f"Error: {blocked}"

    syntax_err = validate_syntax(path, content)
    if syntax_err:
        return f"Error: {syntax_err}"

    _staged_files[path.lstrip("/")] = content
    return f"Staged: {path} ({len(content)} chars, {content.count(chr(10))+1} lines)"


def get_staged_summary() -> str:
    """Return a summary of all staged files."""
    if not _staged_files:
        return "No files staged."
    lines = [f"Staged files ({len(_staged_files)}):"]
    for path, content in _staged_files.items():
        lines.append(f"  - {path} ({len(content)} chars)")
    return "\n".join(lines)


def clear_staged() -> str:
    """Clear the staging area."""
    count = len(_staged_files)
    _staged_files.clear()
    return f"Cleared {count} staged file(s)."


async def deploy_changes(commit_message: str, max_retries: int = 3) -> dict[str, Any]:
    """Commit all staged files atomically via GitHub Git Data API.

    Flow: create blobs -> create tree -> create commit -> update ref.
    Retries on 422 (non-fast-forward) — handles the race condition where a
    developer pushes between reading the ref and updating it.

    Returns {"commit_sha": str, "files": list} on success,
    or {"error": str} on failure.
    """
    if not settings.github_token:
        return {"error": "GITHUB_TOKEN not configured."}

    if not _staged_files:
        return {"error": "No files staged. Use edit_own_code first."}

    headers = _api_headers()
    base = _api_base()
    last_error = ""

    for attempt in range(max_retries):
        if attempt > 0:
            backoff = attempt  # 1s, 2s
            logger.info(f"deploy_changes retry {attempt}/{max_retries} after {backoff}s backoff")
            import asyncio
            await asyncio.sleep(backoff)

        async with httpx.AsyncClient(timeout=60) as client:
            # 1. Get the current commit SHA for the branch
            ref_url = f"{base}/git/ref/heads/{settings.github_branch}"
            resp = await client.get(ref_url, headers=headers)
            if resp.status_code != 200:
                last_error = f"Failed to get branch ref: {resp.status_code} {resp.text[:300]}"
                continue
            current_commit_sha = resp.json()["object"]["sha"]

            # 2. Get the tree SHA of the current commit
            commit_url = f"{base}/git/commits/{current_commit_sha}"
            resp = await client.get(commit_url, headers=headers)
            if resp.status_code != 200:
                last_error = f"Failed to get commit: {resp.status_code} {resp.text[:300]}"
                continue
            base_tree_sha = resp.json()["tree"]["sha"]

            # 3. Create blobs for each staged file
            tree_items = []
            blob_failed = False
            for path, content in _staged_files.items():
                blob_url = f"{base}/git/blobs"
                resp = await client.post(
                    blob_url,
                    headers=headers,
                    json={"content": content, "encoding": "utf-8"},
                )
                if resp.status_code != 201:
                    last_error = f"Failed to create blob for {path}: {resp.status_code} {resp.text[:300]}"
                    blob_failed = True
                    break
                blob_sha = resp.json()["sha"]
                tree_items.append({
                    "path": path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob_sha,
                })
            if blob_failed:
                continue

            # 4. Create a new tree with the staged files
            tree_url = f"{base}/git/trees"
            resp = await client.post(
                tree_url,
                headers=headers,
                json={"base_tree": base_tree_sha, "tree": tree_items},
            )
            if resp.status_code != 201:
                last_error = f"Failed to create tree: {resp.status_code} {resp.text[:300]}"
                continue
            new_tree_sha = resp.json()["sha"]

            # 5. Create a new commit
            commit_create_url = f"{base}/git/commits"
            resp = await client.post(
                commit_create_url,
                headers=headers,
                json={
                    "message": commit_message,
                    "tree": new_tree_sha,
                    "parents": [current_commit_sha],
                },
            )
            if resp.status_code != 201:
                last_error = f"Failed to create commit: {resp.status_code} {resp.text[:300]}"
                continue
            new_commit_sha = resp.json()["sha"]

            # 6. Update the branch ref to point to the new commit
            resp = await client.patch(
                ref_url,
                headers=headers,
                json={"sha": new_commit_sha},
            )
            if resp.status_code == 422:
                # Non-fast-forward — another push landed between our read and update
                logger.warning(
                    f"deploy_changes: non-fast-forward on attempt {attempt + 1}, "
                    f"retrying with latest ref"
                )
                last_error = "Non-fast-forward: branch was updated by another push"
                continue
            if resp.status_code != 200:
                last_error = f"Failed to update ref: {resp.status_code} {resp.text[:300]}"
                continue

            # Success — clear staging area
            deployed_files = list(_staged_files.keys())
            _staged_files.clear()

            if attempt > 0:
                logger.info(f"deploy_changes succeeded on retry {attempt}")

            logger.info(f"Deployed {len(deployed_files)} file(s) in commit {new_commit_sha[:8]}: {deployed_files}")

            return {
                "commit_sha": new_commit_sha,
                "files": deployed_files,
                "message": commit_message,
            }

    # All retries exhausted
    return {"error": f"deploy_changes failed after {max_retries} attempts. Last error: {last_error}"}
