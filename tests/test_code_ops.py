"""Tests for code_ops.py — path blocking and per-agent staging."""

import pytest

from chief_of_staff.agent.code_ops import (
    is_path_blocked,
    stage_file,
    get_staged_summary,
    clear_staged,
    _staged_files_by_agent,
)


class TestPathBlocking:
    """Verify blocked path patterns catch all attack vectors."""

    def test_dotenv_exact(self):
        assert is_path_blocked(".env") is not None

    def test_dotenv_nested(self):
        """Nested .env in a subdirectory should be blocked."""
        assert is_path_blocked("src/.env/sneaky.py") is not None

    def test_credentials_json(self):
        assert is_path_blocked("credentials.json") is not None

    def test_token_json(self):
        assert is_path_blocked("token.json") is not None

    def test_git_dir(self):
        assert is_path_blocked(".git/config") is not None

    def test_venv_dir(self):
        assert is_path_blocked("venv/lib/site-packages/foo.py") is not None

    def test_chroma_data(self):
        assert is_path_blocked("chroma_data/something.bin") is not None

    def test_db_extension(self):
        assert is_path_blocked("data/mydata.db") is not None

    def test_leading_slash_stripped(self):
        assert is_path_blocked("/.env") is not None

    def test_normal_python_file_allowed(self):
        assert is_path_blocked("src/chief_of_staff/agent/core.py") is None

    def test_yaml_file_allowed(self):
        assert is_path_blocked("agents/chief_of_staff.yaml") is None


class TestPerAgentStaging:
    """Verify agents have isolated staging areas."""

    def setup_method(self):
        _staged_files_by_agent.clear()

    def test_agents_isolated(self):
        """Two agents staging files should not see each other's files."""
        stage_file("file_a.py", "print('a')\n", agent_name="agent_a")
        stage_file("file_b.py", "print('b')\n", agent_name="agent_b")

        summary_a = get_staged_summary(agent_name="agent_a")
        summary_b = get_staged_summary(agent_name="agent_b")

        assert "file_a.py" in summary_a
        assert "file_b.py" not in summary_a
        assert "file_b.py" in summary_b
        assert "file_a.py" not in summary_b

    def test_clear_only_clears_own_agent(self):
        stage_file("file_a.py", "print('a')\n", agent_name="agent_a")
        stage_file("file_b.py", "print('b')\n", agent_name="agent_b")

        clear_staged(agent_name="agent_a")

        assert get_staged_summary(agent_name="agent_a") == "No files staged."
        assert "file_b.py" in get_staged_summary(agent_name="agent_b")

    def test_syntax_validation_rejects_bad_python(self):
        result = stage_file("bad.py", "def broken(\n", agent_name="test")
        assert "Error" in result

    def test_blocked_path_rejected(self):
        result = stage_file(".env", "SECRET=xxx\n", agent_name="test")
        assert "Error" in result
        assert "Blocked" in result

    def test_staging_valid_file(self):
        result = stage_file("ok.py", "x = 1\n", agent_name="test")
        assert "Staged" in result
