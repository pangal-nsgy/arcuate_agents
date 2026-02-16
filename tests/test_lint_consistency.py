"""Tests for the consistency linter."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# Import linter functions directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from lint_consistency import (
    check_activity_consistency,
    check_agent_yamls,
    check_architecture_changelog,
    check_tools_consistency,
    _get_defined_tool_names,
    _get_defined_skill_names,
    REPO_ROOT,
)


class TestToolsConsistency:
    """Test skill module definition vs handler checks."""

    def test_current_codebase_passes(self):
        """The current codebase should have matching definitions and handlers."""
        errors = check_tools_consistency()
        assert errors == [], f"Tools consistency errors: {errors}"

    def test_skills_dir_exists(self):
        """skills/ directory must exist."""
        skills_dir = REPO_ROOT / "src" / "chief_of_staff" / "agent" / "skills"
        assert skills_dir.is_dir(), f"skills/ not found at {skills_dir}"

    def test_all_21_tools_defined(self):
        """Verify the expected 27 tools are defined across skill modules."""
        tool_names = _get_defined_tool_names()
        expected_tools = [
            "search_knowledge", "send_sms", "send_email", "draft_document",
            "list_recent_emails", "search_meetings", "research_practice", "catch_me_up", "send_meeting_bot",
            "show_current_prompt", "update_own_instructions", "update_system_prompt", "update_triage_config",
            "remember", "recall_memory", "create_sub_agent", "delegate_task",
            "read_own_code", "edit_own_code", "deploy_changes",
            "create_task_plan", "execute_task_plan", "scaffold_skill",
            "run_python", "fetch_webpage", "install_package", "report_progress",
        ]
        for tool in expected_tools:
            assert tool in tool_names, f"Tool '{tool}' not found in skill modules"

    def test_all_8_skills_defined(self):
        """Verify the expected 8 skills are defined."""
        skill_names = _get_defined_skill_names()
        expected_skills = [
            "knowledge", "communication", "meetings", "self_mod",
            "memory", "delegation", "code_ops", "orchestration",
        ]
        for skill in expected_skills:
            assert skill in skill_names, f"Skill '{skill}' not found in skill modules"


class TestActivityConsistency:
    """Test activity.py constant vs stats checks."""

    def test_current_codebase_passes(self):
        """All action constants should be referenced in get_activity_stats()."""
        errors = check_activity_consistency()
        assert errors == [], f"Activity consistency errors: {errors}"

    def test_activity_file_exists(self):
        """activity.py must exist."""
        activity_path = REPO_ROOT / "src" / "chief_of_staff" / "agent" / "activity.py"
        assert activity_path.exists()


class TestAgentYamls:
    """Test agent YAML validation."""

    def test_current_codebase_passes(self):
        """All agent YAMLs should be valid."""
        errors = check_agent_yamls()
        assert errors == [], f"Agent YAML errors: {errors}"

    def test_chief_of_staff_yaml_exists(self):
        """The main agent YAML must exist."""
        yaml_path = REPO_ROOT / "agents" / "chief_of_staff.yaml"
        assert yaml_path.exists()

    def test_chief_of_staff_has_all_required_fields(self):
        """chief_of_staff.yaml should have all required fields."""
        import yaml
        yaml_path = REPO_ROOT / "agents" / "chief_of_staff.yaml"
        data = yaml.safe_load(yaml_path.read_text())
        required = ["name", "display_name", "model", "max_tokens",
                     "max_iterations", "system_prompt", "permissions"]
        for field in required:
            assert field in data, f"Missing required field: {field}"


class TestArchitectureChangelog:
    """Test architecture_changelog.yaml validation."""

    def test_current_codebase_passes(self):
        """The changelog should be valid."""
        errors = check_architecture_changelog()
        assert errors == [], f"Changelog errors: {errors}"

    def test_changelog_exists(self):
        """architecture_changelog.yaml must exist."""
        path = REPO_ROOT / "architecture_changelog.yaml"
        assert path.exists()


class TestLinterCLI:
    """Test the linter runs as a script."""

    def test_runs_successfully(self):
        """The linter should exit 0 on the current codebase."""
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "lint_consistency.py")],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, f"Linter failed:\n{result.stdout}\n{result.stderr}"

    def test_verbose_flag(self):
        """--verbose should produce more output."""
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "lint_consistency.py"), "--verbose"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0
        assert "[info]" in result.stdout
