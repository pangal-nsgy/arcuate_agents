#!/usr/bin/env python3
"""Consistency linter for the Arcuate Chief of Staff codebase.

Standalone script — no app imports. Checks:
  1. skills/*.py: every tool in TOOL_DEFINITIONS has a handler in execute(), and vice versa
  2. activity.py: all action type constants are referenced in get_activity_stats()
  3. agents/*.yaml: valid YAML, required fields present, tool names exist in skills
  4. architecture_changelog.yaml: valid YAML, entries have required fields

Usage: python scripts/lint_consistency.py [--verbose]
Exit code 0 = all checks pass, 1 = failures found.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import yaml


def find_repo_root() -> Path:
    """Walk up from this script to find the repo root (contains src/)."""
    path = Path(__file__).resolve().parent
    while path != path.parent:
        if (path / "src").is_dir():
            return path
        path = path.parent
    # Fallback: assume script is in scripts/ under repo root
    return Path(__file__).resolve().parent.parent


REPO_ROOT = find_repo_root()
VERBOSE = "--verbose" in sys.argv or "-v" in sys.argv


def log(msg: str) -> None:
    if VERBOSE:
        print(f"  [info] {msg}")


def error(msg: str) -> str:
    print(f"  [FAIL] {msg}")
    return msg


# ---------------------------------------------------------------------------
# Check 1: skills/*.py — definitions vs handlers
# ---------------------------------------------------------------------------

def _get_skill_files() -> list[Path]:
    """Get all skill module files (excluding __init__.py)."""
    skills_dir = REPO_ROOT / "src" / "chief_of_staff" / "agent" / "skills"
    if not skills_dir.is_dir():
        return []
    return [f for f in skills_dir.glob("*.py") if f.name != "__init__.py"]


def _parse_tool_definitions_from_module(source: str) -> set[str]:
    """Extract tool names from TOOL_DEFINITIONS dict in a skill module."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        target_name = None
        value = None
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "TOOL_DEFINITIONS":
                    target_name = target.id
                    value = node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "TOOL_DEFINITIONS":
                target_name = node.target.id
                value = node.value

        if target_name and isinstance(value, ast.Dict):
            for key in value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    names.add(key.value)
    return names


def _parse_handled_tools_from_module(source: str) -> set[str]:
    """Extract tool names handled in execute() via name == '...' comparisons."""
    pattern = re.compile(r'name\s*==\s*["\'](\w+)["\']')
    return set(pattern.findall(source))


def check_tools_consistency() -> list[str]:
    """Verify every tool definition has a handler and vice versa, across all skill modules."""
    errors: list[str] = []
    skill_files = _get_skill_files()

    if not skill_files:
        return [error("No skill modules found in skills/")]

    all_defined: set[str] = set()
    all_handled: set[str] = set()

    for skill_file in skill_files:
        source = skill_file.read_text()
        defined = _parse_tool_definitions_from_module(source)
        handled = _parse_handled_tools_from_module(source)

        all_defined |= defined
        all_handled |= handled

        log(f"{skill_file.name}: {len(defined)} defined, {len(handled)} handled")

        # Per-module check: tools defined in this module should be handled here
        defined_only = defined - handled
        handled_only = handled - defined

        for tool in sorted(defined_only):
            errors.append(error(f"{skill_file.name}: tool '{tool}' is defined but has no handler"))
        for tool in sorted(handled_only):
            errors.append(error(f"{skill_file.name}: tool '{tool}' has a handler but is not defined"))

    log(f"Total: {len(all_defined)} tools defined, {len(all_handled)} tools handled")

    return errors


# ---------------------------------------------------------------------------
# Check 2: activity.py — constants vs get_activity_stats()
# ---------------------------------------------------------------------------

def check_activity_consistency() -> list[str]:
    """Verify all action type constants are used in get_activity_stats()."""
    errors: list[str] = []
    activity_path = REPO_ROOT / "src" / "chief_of_staff" / "agent" / "activity.py"

    if not activity_path.exists():
        return [error(f"activity.py not found at {activity_path}")]

    source = activity_path.read_text()
    tree = ast.parse(source, filename=str(activity_path))

    # Find module-level string constants (UPPER_CASE = "value")
    action_constants: dict[str, str] = {}  # name -> value
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if (
                isinstance(target, ast.Name)
                and target.id.isupper()
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                # Skip non-action-type constants like ACTIVITY_SCHEMA
                if target.id in ("ACTIVITY_SCHEMA",):
                    continue
                action_constants[target.id] = node.value.value

    if not action_constants:
        return [error("Could not find action type constants in activity.py")]

    log(f"Found {len(action_constants)} action constants: {sorted(action_constants)}")

    # Find references in get_activity_stats function body
    stats_fn_source = _extract_function_source(source, "get_activity_stats")
    if not stats_fn_source:
        return [error("Could not find get_activity_stats() in activity.py")]

    unreferenced = []
    for const_name in sorted(action_constants):
        if const_name not in stats_fn_source:
            unreferenced.append(const_name)

    for name in unreferenced:
        errors.append(error(
            f"Action constant '{name}' ({action_constants[name]}) "
            f"is not referenced in get_activity_stats()"
        ))

    return errors


def _extract_function_source(source: str, func_name: str) -> str | None:
    """Extract the source text of a function by name."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            lines = source.splitlines()
            start = node.lineno - 1
            end = node.end_lineno if node.end_lineno else start + 1
            return "\n".join(lines[start:end])
    return None


# ---------------------------------------------------------------------------
# Check 3: agents/*.yaml — valid YAML, required fields, tool names
# ---------------------------------------------------------------------------

REQUIRED_AGENT_FIELDS = [
    "name", "display_name", "model", "max_tokens", "max_iterations",
    "system_prompt", "permissions",
]

REQUIRED_PERMISSION_FIELDS = [
    "can_self_modify", "can_create_agents", "can_send_external", "can_modify_code",
]


def check_agent_yamls() -> list[str]:
    """Validate all agent YAML configs."""
    errors: list[str] = []
    agents_dir = REPO_ROOT / "agents"

    if not agents_dir.is_dir():
        return [error(f"agents/ directory not found at {agents_dir}")]

    yaml_files = list(agents_dir.glob("*.yaml")) + list(agents_dir.glob("*.yml"))

    if not yaml_files:
        return [error("No YAML files found in agents/")]

    # Get valid tool names from skill modules
    valid_tools = _get_defined_tool_names()
    # Get valid skill names from skill modules
    valid_skills = _get_defined_skill_names()

    for yaml_file in yaml_files:
        log(f"Checking {yaml_file.name}")
        try:
            data = yaml.safe_load(yaml_file.read_text())
        except yaml.YAMLError as e:
            errors.append(error(f"{yaml_file.name}: YAML parse error: {e}"))
            continue

        if not isinstance(data, dict):
            errors.append(error(f"{yaml_file.name}: expected a YAML mapping, got {type(data).__name__}"))
            continue

        # Required fields (tools OR skills must be present)
        for field in REQUIRED_AGENT_FIELDS:
            if field not in data:
                errors.append(error(f"{yaml_file.name}: missing required field '{field}'"))

        has_tools = "tools" in data and data["tools"]
        has_skills = "skills" in data and data["skills"]
        if not has_tools and not has_skills:
            errors.append(error(f"{yaml_file.name}: must have either 'tools' or 'skills'"))

        # Permissions sub-fields
        perms = data.get("permissions", {})
        if isinstance(perms, dict):
            for field in REQUIRED_PERMISSION_FIELDS:
                if field not in perms:
                    errors.append(error(f"{yaml_file.name}: permissions missing '{field}'"))

        # Tool names must exist in skill modules
        tools = data.get("tools", [])
        if isinstance(tools, list) and valid_tools:
            for tool_name in tools:
                if tool_name not in valid_tools:
                    errors.append(error(
                        f"{yaml_file.name}: tool '{tool_name}' not found in skill modules"
                    ))

        # Skill names must be valid
        skills = data.get("skills", [])
        if isinstance(skills, list) and valid_skills:
            for skill_name in skills:
                # Allow both skill names and individual tool names in skills list
                if skill_name not in valid_skills and skill_name not in valid_tools:
                    errors.append(error(
                        f"{yaml_file.name}: skill '{skill_name}' not found"
                    ))

    return errors


def _get_defined_tool_names() -> set[str]:
    """Parse tool names from TOOL_DEFINITIONS in all skill modules."""
    names: set[str] = set()
    for skill_file in _get_skill_files():
        source = skill_file.read_text()
        names |= _parse_tool_definitions_from_module(source)
    return names


def _get_defined_skill_names() -> set[str]:
    """Parse SKILL_NAME values from all skill modules."""
    names: set[str] = set()
    for skill_file in _get_skill_files():
        source = skill_file.read_text()
        tree = ast.parse(source)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if (
                    isinstance(target, ast.Name)
                    and target.id == "SKILL_NAME"
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    names.add(node.value.value)
    return names


# ---------------------------------------------------------------------------
# Check 4: architecture_changelog.yaml — valid YAML, required fields
# ---------------------------------------------------------------------------

REQUIRED_CHANGELOG_FIELDS = ["date", "author", "category", "title"]
VALID_CATEGORIES = {"tools", "modules", "integrations", "config", "deployment", "security"}


def check_architecture_changelog() -> list[str]:
    """Validate architecture_changelog.yaml format."""
    errors: list[str] = []
    changelog_path = REPO_ROOT / "architecture_changelog.yaml"

    if not changelog_path.exists():
        return [error(f"architecture_changelog.yaml not found at {changelog_path}")]

    try:
        data = yaml.safe_load(changelog_path.read_text())
    except yaml.YAMLError as e:
        return [error(f"architecture_changelog.yaml: YAML parse error: {e}")]

    if not isinstance(data, list):
        return [error(f"architecture_changelog.yaml: expected a list, got {type(data).__name__}")]

    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            errors.append(error(f"architecture_changelog.yaml entry {i}: expected a mapping"))
            continue

        for field in REQUIRED_CHANGELOG_FIELDS:
            if field not in entry:
                errors.append(error(
                    f"architecture_changelog.yaml entry {i}: missing required field '{field}'"
                ))

        category = entry.get("category", "")
        if category and category not in VALID_CATEGORIES:
            errors.append(error(
                f"architecture_changelog.yaml entry {i}: "
                f"invalid category '{category}' (valid: {sorted(VALID_CATEGORIES)})"
            ))

    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    """Run all consistency checks. Returns 0 on success, 1 on failure."""
    print("Collaboration Guardian — Consistency Linter")
    print("=" * 50)

    all_errors: list[str] = []

    checks = [
        ("Tools (definitions vs handlers)", check_tools_consistency),
        ("Activity (constants vs stats)", check_activity_consistency),
        ("Agent YAMLs (structure + tools)", check_agent_yamls),
        ("Architecture changelog", check_architecture_changelog),
    ]

    for name, check_fn in checks:
        print(f"\n[check] {name}")
        errors = check_fn()
        all_errors.extend(errors)
        if not errors:
            print("  [PASS]")

    print(f"\n{'=' * 50}")
    if all_errors:
        print(f"FAILED: {len(all_errors)} error(s) found")
        return 1
    else:
        print("ALL CHECKS PASSED")
        return 0


if __name__ == "__main__":
    sys.exit(main())
