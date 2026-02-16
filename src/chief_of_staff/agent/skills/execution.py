"""Execution skill — run Python code, fetch webpages, install packages, report progress."""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import re
import subprocess
import sys
import tempfile
from typing import Any

SKILL_NAME = "execution"

logger = logging.getLogger(__name__)

# Env var patterns to strip from subprocess environment (case-insensitive suffixes)
_SECRET_PATTERNS = re.compile(
    r"(_KEY|_TOKEN|_SECRET|_PASSWORD|_CREDENTIAL)$", re.IGNORECASE
)

# Explicit env vars to always strip
_EXPLICIT_SECRETS = {
    "ANTHROPIC_API_KEY",
    "DISCORD_BOT_TOKEN",
    "GITHUB_TOKEN",
    "GH_PAT",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_ACCOUNT_SID",
    "GOOGLE_CREDENTIALS_JSON",
    "GOOGLE_TOKEN_JSON",
    "ELEVENLABS_API_KEY",
    "RECALL_API_KEY",
    "ZOOM_CLIENT_SECRET",
    "DISCORD_WEBHOOK_URL",
}

# Allowed package name pattern (alphanumeric, hyphens, dots, version specifiers)
_PACKAGE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*(\[.+\])?(==|>=|<=|!=|~=|>|<)?[a-zA-Z0-9.*]*$")

# Max timeout for run_python (seconds)
_MAX_TIMEOUT = 120


TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "run_python": {
        "name": "run_python",
        "description": (
            "Execute Python code in an isolated subprocess. The code runs in a fresh temp directory "
            "with secrets stripped from the environment. Use this for data processing, scraping, "
            "API calls, calculations, file generation, and anything not covered by other tools. "
            "Pre-installed: httpx, beautifulsoup4, lxml, json, csv, re. "
            "Use install_package first if you need additional packages. "
            "Max timeout: 120 seconds."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute. Use print() to return output.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (max 120, default 60).",
                },
            },
            "required": ["code"],
        },
    },
    "fetch_webpage": {
        "name": "fetch_webpage",
        "description": (
            "Fetch a URL and return its text content. Uses httpx with a browser user-agent, "
            "follows redirects. HTML is converted to clean text via BeautifulSoup. "
            "Returns first 50,000 characters. For JavaScript-heavy sites, use web_search instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch.",
                },
                "include_links": {
                    "type": "boolean",
                    "description": "If true, preserve hyperlinks as [text](url) in output. Default false.",
                },
            },
            "required": ["url"],
        },
    },
    "install_package": {
        "name": "install_package",
        "description": (
            "Install a Python package via pip. Use this before run_python if you need a package "
            "that isn't pre-installed. Package name is validated — no shell injection possible."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "package": {
                    "type": "string",
                    "description": "Package name with optional version (e.g., 'pandas', 'requests>=2.28').",
                },
            },
            "required": ["package"],
        },
    },
    "report_progress": {
        "name": "report_progress",
        "description": (
            "Post a status update during a long multi-step task. Use this to keep the user "
            "informed about what you're doing, especially during scraping or data processing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Current status message (e.g., 'Scraped 3/10 pages, processing...').",
                },
                "step": {
                    "type": "integer",
                    "description": "Current step number (optional).",
                },
                "total_steps": {
                    "type": "integer",
                    "description": "Total number of steps (optional).",
                },
            },
            "required": ["status"],
        },
    },
}


def _make_clean_env() -> dict[str, str]:
    """Build a subprocess environment with all secrets stripped."""
    env = {}
    for key, value in os.environ.items():
        if key in _EXPLICIT_SECRETS:
            continue
        if _SECRET_PATTERNS.search(key):
            continue
        env[key] = value
    return env


async def execute(name: str, args: dict[str, Any], agent_name: str) -> str:
    """Execute an execution tool. May raise — caller handles exceptions."""
    if name == "run_python":
        return await _run_python(args, agent_name)
    elif name == "fetch_webpage":
        return await _fetch_webpage(args, agent_name)
    elif name == "install_package":
        return await _install_package(args, agent_name)
    elif name == "report_progress":
        return await _report_progress(args, agent_name)
    else:
        raise ValueError(f"Unknown execution tool: {name}")


async def _run_python(args: dict[str, Any], agent_name: str) -> str:
    """Execute Python code in an isolated subprocess."""
    from chief_of_staff.agent.activity import log_activity, PYTHON_EXEC

    code = args["code"]
    timeout = min(args.get("timeout", 60), _MAX_TIMEOUT)

    clean_env = _make_clean_env()

    def _run() -> tuple[str, str, int]:
        with tempfile.TemporaryDirectory(prefix="arcuate_exec_") as tmpdir:
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tmpdir,
                env=clean_env,
            )
            return result.stdout, result.stderr, result.returncode

    try:
        loop = asyncio.get_event_loop()
        stdout, stderr, returncode = await loop.run_in_executor(
            None, functools.partial(_run)
        )
    except subprocess.TimeoutExpired:
        log_activity(
            agent_name=agent_name,
            action_type=PYTHON_EXEC,
            action_detail="timeout",
            input_summary=code[:500],
            output_summary=f"Timed out after {timeout}s",
        )
        return f"Execution timed out after {timeout} seconds."

    # Truncate output to reasonable size
    stdout = stdout[:50000] if stdout else ""
    stderr = stderr[:10000] if stderr else ""

    log_activity(
        agent_name=agent_name,
        action_type=PYTHON_EXEC,
        action_detail=f"exit_code={returncode}",
        input_summary=code[:500],
        output_summary=(stdout[:300] + stderr[:200]) if stdout or stderr else "no output",
    )

    if returncode == 0:
        return stdout if stdout else "(no output)"
    else:
        output = ""
        if stdout:
            output += f"STDOUT:\n{stdout}\n"
        if stderr:
            output += f"STDERR:\n{stderr}\n"
        return f"Exited with code {returncode}.\n{output}" if output else f"Exited with code {returncode} (no output)."


async def _fetch_webpage(args: dict[str, Any], agent_name: str) -> str:
    """Fetch a URL and return cleaned text content."""
    import httpx
    from bs4 import BeautifulSoup
    from chief_of_staff.agent.activity import log_activity, WEBPAGE_FETCH

    url = args["url"]
    include_links = args.get("include_links", False)

    # Basic URL validation
    if not url.startswith(("http://", "https://")):
        return "Invalid URL — must start with http:// or https://"

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            },
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.HTTPStatusError as e:
        log_activity(
            agent_name=agent_name,
            action_type=WEBPAGE_FETCH,
            action_detail=f"http_error_{e.response.status_code}",
            input_summary=url,
        )
        return f"HTTP error {e.response.status_code} fetching {url}"
    except Exception as e:
        log_activity(
            agent_name=agent_name,
            action_type=WEBPAGE_FETCH,
            action_detail="fetch_error",
            input_summary=url,
            output_summary=str(e)[:500],
        )
        return f"Failed to fetch {url}: {e}"

    content_type = response.headers.get("content-type", "")

    if "html" in content_type or not content_type:
        soup = BeautifulSoup(response.text, "lxml")
        # Remove script and style elements
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        if include_links:
            # Preserve links as markdown
            for a in soup.find_all("a", href=True):
                a.replace_with(f"[{a.get_text()}]({a['href']})")

        text = soup.get_text(separator="\n", strip=True)
    else:
        text = response.text

    # Truncate to 50k chars
    text = text[:50000]

    log_activity(
        agent_name=agent_name,
        action_type=WEBPAGE_FETCH,
        action_detail=f"fetched_{len(text)}_chars",
        input_summary=url,
        output_summary=text[:300],
    )

    return text if text.strip() else "(page returned no text content)"


async def _install_package(args: dict[str, Any], agent_name: str) -> str:
    """Install a Python package via pip."""
    from chief_of_staff.agent.activity import log_activity, PACKAGE_INSTALL

    package = args["package"].strip()

    # Validate package name to prevent shell injection
    if not _PACKAGE_RE.match(package):
        return f"Invalid package name: '{package}'. Only alphanumeric, hyphens, dots, and version specifiers allowed."

    # Extra safety: reject anything with shell metacharacters
    if any(c in package for c in ";|&$`\\'\"\n\r\t{}()"):
        return f"Invalid package name: '{package}'. Contains forbidden characters."

    def _install() -> tuple[str, str, int]:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", package],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.stdout, result.stderr, result.returncode

    try:
        loop = asyncio.get_event_loop()
        stdout, stderr, returncode = await loop.run_in_executor(None, _install)
    except subprocess.TimeoutExpired:
        log_activity(
            agent_name=agent_name,
            action_type=PACKAGE_INSTALL,
            action_detail="timeout",
            input_summary=package,
        )
        return f"Package install timed out after 120s: {package}"

    log_activity(
        agent_name=agent_name,
        action_type=PACKAGE_INSTALL,
        action_detail=f"exit_code={returncode}",
        input_summary=package,
        output_summary=(stdout[-300:] if stdout else "") + (stderr[-200:] if stderr else ""),
    )

    if returncode == 0:
        return f"Successfully installed {package}."
    else:
        return f"Failed to install {package}.\n{stderr[:2000]}" if stderr else f"Failed to install {package} (exit code {returncode})."


async def _report_progress(args: dict[str, Any], agent_name: str) -> str:
    """Log a progress update and forward it to Discord via emit_progress."""
    from chief_of_staff.agent.activity import log_activity, PROGRESS_REPORT
    from chief_of_staff.agent.request_context import emit_progress

    status = args["status"]
    step = args.get("step")
    total_steps = args.get("total_steps")

    detail = status
    if step is not None and total_steps is not None:
        detail = f"[{step}/{total_steps}] {status}"

    log_activity(
        agent_name=agent_name,
        action_type=PROGRESS_REPORT,
        action_detail=detail,
        output_summary=status,
    )

    await emit_progress(detail)

    return f"Progress reported: {detail}"
