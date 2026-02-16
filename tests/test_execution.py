"""Tests for the execution skill — run_python, fetch_webpage, install_package, report_progress."""

from __future__ import annotations

import os
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from chief_of_staff.agent.skills import SkillRegistry
from chief_of_staff.agent.skills.execution import (
    SKILL_NAME,
    TOOL_DEFINITIONS,
    _make_clean_env,
    _PACKAGE_RE,
    execute,
)


class TestExecutionRegistration:
    """Test that the execution skill registers correctly."""

    def test_skill_name(self):
        assert SKILL_NAME == "execution"

    def test_has_four_tools(self):
        assert len(TOOL_DEFINITIONS) == 4
        assert "run_python" in TOOL_DEFINITIONS
        assert "fetch_webpage" in TOOL_DEFINITIONS
        assert "install_package" in TOOL_DEFINITIONS
        assert "report_progress" in TOOL_DEFINITIONS

    def test_registered_in_skill_registry(self):
        registry = SkillRegistry()
        registry._ensure_loaded()
        assert "execution" in registry._skills
        for tool in ["run_python", "fetch_webpage", "install_package", "report_progress"]:
            assert tool in registry._tool_map, f"Tool '{tool}' not in registry"


class TestCleanEnv:
    """Test environment sanitization for subprocess execution."""

    def test_strips_explicit_secrets(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test", "HOME": "/home/test"}, clear=True):
            env = _make_clean_env()
            assert "ANTHROPIC_API_KEY" not in env
            assert env.get("HOME") == "/home/test"

    def test_strips_pattern_matched_secrets(self):
        with patch.dict(os.environ, {"MY_CUSTOM_API_KEY": "secret123", "PATH": "/usr/bin"}, clear=True):
            env = _make_clean_env()
            assert "MY_CUSTOM_API_KEY" not in env
            assert "PATH" in env

    def test_strips_token_pattern(self):
        with patch.dict(os.environ, {"SOME_SERVICE_TOKEN": "tok123", "LANG": "en_US"}, clear=True):
            env = _make_clean_env()
            assert "SOME_SERVICE_TOKEN" not in env
            assert "LANG" in env


class TestRunPython:
    """Test the run_python tool."""

    @pytest.mark.asyncio
    async def test_simple_print(self):
        result = await execute("run_python", {"code": "print('hello world')"}, "test")
        assert "hello world" in result

    @pytest.mark.asyncio
    async def test_syntax_error(self):
        result = await execute("run_python", {"code": "def f(:"}, "test")
        assert "SyntaxError" in result or "Exited with code" in result

    @pytest.mark.asyncio
    async def test_timeout_clamped_to_max(self):
        """Timeout should be clamped to _MAX_TIMEOUT (120s)."""
        result = await execute("run_python", {"code": "print('fast')", "timeout": 999}, "test")
        assert "fast" in result

    @pytest.mark.asyncio
    async def test_secrets_not_in_env(self):
        """ANTHROPIC_API_KEY should not be visible from subprocess."""
        code = """
import os
key = os.environ.get('ANTHROPIC_API_KEY', 'NOT_FOUND')
print(key)
"""
        result = await execute("run_python", {"code": code}, "test")
        assert "NOT_FOUND" in result

    @pytest.mark.asyncio
    async def test_multi_line_output(self):
        code = "for i in range(3): print(f'line {i}')"
        result = await execute("run_python", {"code": code}, "test")
        assert "line 0" in result
        assert "line 2" in result

    @pytest.mark.asyncio
    async def test_no_output(self):
        result = await execute("run_python", {"code": "x = 1 + 1"}, "test")
        assert "(no output)" in result


class TestFetchWebpage:
    """Test the fetch_webpage tool."""

    @pytest.mark.asyncio
    async def test_invalid_url_rejected(self):
        result = await execute("fetch_webpage", {"url": "not-a-url"}, "test")
        assert "Invalid URL" in result

    @pytest.mark.asyncio
    async def test_ftp_url_rejected(self):
        result = await execute("fetch_webpage", {"url": "ftp://example.com"}, "test")
        assert "Invalid URL" in result

    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        """Mocked fetch returns parsed HTML content."""
        mock_response = MagicMock()
        mock_response.text = "<html><body><h1>Hello</h1><p>World</p></body></html>"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await execute("fetch_webpage", {"url": "https://example.com"}, "test")

        assert "Hello" in result
        assert "World" in result


class TestInstallPackage:
    """Test the install_package tool."""

    def test_valid_package_names(self):
        assert _PACKAGE_RE.match("requests")
        assert _PACKAGE_RE.match("beautifulsoup4")
        assert _PACKAGE_RE.match("pandas>=1.5.0")
        assert _PACKAGE_RE.match("my-package==2.0")
        assert _PACKAGE_RE.match("lxml")

    def test_invalid_package_names(self):
        # These should NOT match (shell injection attempts)
        assert not _PACKAGE_RE.match("; rm -rf /")
        assert not _PACKAGE_RE.match("pkg && evil")
        assert not _PACKAGE_RE.match("")

    @pytest.mark.asyncio
    async def test_shell_metacharacter_rejected(self):
        result = await execute("install_package", {"package": "pkg; rm -rf /"}, "test")
        assert "Invalid package name" in result

    @pytest.mark.asyncio
    async def test_backtick_rejected(self):
        result = await execute("install_package", {"package": "pkg`whoami`"}, "test")
        assert "Invalid package name" in result

    @pytest.mark.asyncio
    async def test_pipe_rejected(self):
        result = await execute("install_package", {"package": "pkg | cat /etc/passwd"}, "test")
        assert "Invalid package name" in result


class TestReportProgress:
    """Test the report_progress tool."""

    @pytest.mark.asyncio
    async def test_basic_progress(self):
        result = await execute("report_progress", {"status": "Processing data..."}, "test")
        assert "Progress reported" in result
        assert "Processing data" in result

    @pytest.mark.asyncio
    async def test_progress_with_steps(self):
        result = await execute(
            "report_progress",
            {"status": "Scraping page", "step": 3, "total_steps": 10},
            "test",
        )
        assert "[3/10]" in result
        assert "Scraping page" in result
