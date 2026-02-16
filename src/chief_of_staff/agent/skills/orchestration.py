"""Orchestration skill — explicit planning, execution, and skill scaffolding."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from chief_of_staff.agent.planner import TaskPlan

SKILL_NAME = "orchestration"

TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "create_task_plan": {
        "name": "create_task_plan",
        "description": "Create a structured execution plan for a complex goal. Use this before delegating or executing multi-step work.",
        "input_schema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "High-level goal to accomplish"},
                "tasks": {
                    "type": "array",
                    "description": "Ordered task objects with dependencies and optional tool/agent assignments",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "agent_name": {"type": "string"},
                            "required_skill": {"type": "string"},
                            "tool_name": {"type": "string"},
                            "tool_args": {"type": "object"},
                            "depends_on": {"type": "array", "items": {"type": "integer"}},
                        },
                        "required": ["description"],
                    },
                },
            },
            "required": ["goal"],
        },
    },
    "execute_task_plan": {
        "name": "execute_task_plan",
        "description": "Execute a previously created plan. Steps can run tools directly or delegate to agents. If a required skill is missing, a scaffold can be generated.",
        "input_schema": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "string"},
                "stop_on_error": {"type": "boolean"},
                "auto_scaffold_missing_skills": {"type": "boolean"},
            },
            "required": ["plan_id"],
        },
    },
    "list_available_tools": {
        "name": "list_available_tools",
        "description": (
            "List all tools and skills available in the system. Use this to check what capabilities "
            "exist before spawning or equipping an agent. Returns tool names grouped by skill, plus "
            "a list of all registered agents and their skills."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "include_agents": {
                    "type": "boolean",
                    "description": "Also list all registered agents and their skills (default true).",
                },
            },
        },
    },
    "scaffold_skill": {
        "name": "scaffold_skill",
        "description": "Create a new skill module stub in the codebase, optionally attaching it to an agent's skills list.",
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_name": {"type": "string", "description": "Snake_case skill name"},
                "purpose": {"type": "string", "description": "What the skill should do"},
                "tools": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                        },
                        "required": ["name", "description"],
                    },
                },
                "attach_to_agent": {"type": "string", "description": "Optional agent name to add this skill to"},
            },
            "required": ["skill_name", "purpose"],
        },
    },
}

_PLAN_STORE: dict[str, TaskPlan] = {}


def _normalize_skill_name(name: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9_]+", "_", name.strip().lower())
    base = re.sub(r"_+", "_", base).strip("_")
    if not base:
        raise ValueError("skill_name is empty after normalization")
    return base


def _skill_path(skill_name: str) -> Path:
    return Path(__file__).resolve().parent / f"{skill_name}.py"


def _build_skill_stub(skill_name: str, purpose: str, tools: list[dict[str, str]]) -> str:
    tool_entries: list[str] = []
    for tool in tools:
        tool_name = _normalize_skill_name(tool["name"])
        desc = tool["description"].replace('"', '\\"')
        tool_entries.append(
            f'    "{tool_name}": {{\n'
            f'        "name": "{tool_name}",\n'
            f'        "description": "{desc}",\n'
            '        "input_schema": {"type": "object", "properties": {}},\n'
            "    },"
        )
    if not tool_entries:
        tool_entries = [
            '    "todo_tool": {',
            '        "name": "todo_tool",',
            '        "description": "TODO: implement a concrete tool for this skill.",',
            '        "input_schema": {"type": "object", "properties": {}},',
            "    },",
        ]

    tools_block = "\n".join(tool_entries)
    purpose_escaped = purpose.replace('"', '\\"')
    return f'''"""Auto-generated skill scaffold: {skill_name}."""

from __future__ import annotations

from typing import Any

SKILL_NAME = "{skill_name}"

TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {{
{tools_block}
}}


async def execute(name: str, args: dict[str, Any], agent_name: str) -> str:
    """Execute a tool in {skill_name}.

    Purpose: {purpose_escaped}
    """
    return f"TODO: implement '{{name}}' in skill '{skill_name}'. args={{args}}"
'''


def _agent_has_skill_or_tool(agent_name: str, required: str) -> bool:
    from chief_of_staff.agent.registry import get_registry

    registry = get_registry()
    config = registry.get(agent_name)
    if not config:
        return False
    resolved_tools = set(config.get_resolved_tools())
    return required in set(config.skills) or required in resolved_tools


def _coerce_tasks(goal: str, raw_tasks: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if raw_tasks:
        return raw_tasks

    # Simple fallback: split by " then " and create serial dependencies.
    parts = [p.strip(" .") for p in goal.split(" then ") if p.strip()]
    if len(parts) <= 1:
        parts = [goal.strip()]
    tasks: list[dict[str, Any]] = []
    for i, part in enumerate(parts):
        task: dict[str, Any] = {"description": part}
        if i > 0:
            task["depends_on"] = [i - 1]
        tasks.append(task)
    return tasks


def _list_available_tools(args: dict[str, Any], agent_name: str) -> str:
    """List all tools grouped by skill, and optionally all registered agents."""
    from chief_of_staff.agent.skills import get_skill_registry
    from chief_of_staff.agent.registry import get_registry

    registry = get_skill_registry()
    registry._ensure_loaded()

    # Group tools by skill
    lines: list[str] = ["## Available Skills & Tools\n"]
    for skill_name, skill_mod in sorted(registry._skills.items()):
        tool_names = list(getattr(skill_mod, "TOOL_DEFINITIONS", {}).keys())
        lines.append(f"**{skill_name}** ({len(tool_names)} tools): {', '.join(tool_names)}")
    lines.append(f"\nTotal: {len(registry._tool_map)} tools across {len(registry._skills)} skills")

    include_agents = args.get("include_agents", True)
    if include_agents:
        lines.append("\n## Registered Agents\n")
        agent_registry = get_registry()
        for cfg in agent_registry.list_agents():
            skills_str = ", ".join(cfg.skills) if cfg.skills else "(none)"
            lines.append(
                f"**{cfg.display_name}** (name: {cfg.name}) — "
                f"skills: [{skills_str}], model: {cfg.model}"
            )

    return "\n".join(lines)


async def execute(name: str, args: dict[str, Any], agent_name: str) -> str:
    """Execute an orchestration tool."""
    if name == "list_available_tools":
        return _list_available_tools(args, agent_name)

    elif name == "create_task_plan":
        goal = args.get("goal", "").strip()
        if not goal:
            return "Error: goal is required."

        raw_tasks = args.get("tasks")
        tasks = _coerce_tasks(goal, raw_tasks)
        plan = TaskPlan(goal=goal)

        for task in tasks:
            plan.add_step(
                description=task.get("description", "").strip() or "Unnamed task",
                agent_name=task.get("agent_name", "chief_of_staff"),
                required_skill=task.get("required_skill", ""),
                tool_name=task.get("tool_name"),
                tool_args=task.get("tool_args", {}),
                depends_on=task.get("depends_on", []),
            )

        _PLAN_STORE[plan.plan_id] = plan
        return (
            f"Created plan {plan.plan_id} with {len(plan.steps)} step(s).\n"
            f"{plan.summary}"
        )

    if name == "execute_task_plan":
        plan_id = args.get("plan_id", "")
        plan = _PLAN_STORE.get(plan_id)
        if not plan:
            return f"Error: plan '{plan_id}' not found."

        stop_on_error = bool(args.get("stop_on_error", False))
        auto_scaffold = bool(args.get("auto_scaffold_missing_skills", True))

        from chief_of_staff.agent.core import get_agent, get_agent_by_name
        from chief_of_staff.agent.tools import execute_tool

        while not plan.is_complete:
            ready = plan.get_ready_steps()
            if not ready:
                return (
                    f"Plan stalled: no runnable steps remain.\n"
                    f"{plan.summary}"
                )

            for idx in ready:
                step = plan.steps[idx]
                step.status = "running"

                if step.required_skill and not _agent_has_skill_or_tool(step.agent_name, step.required_skill):
                    scaffold_msg = ""
                    if auto_scaffold:
                        scaffold_msg = await execute(
                            "scaffold_skill",
                            {
                                "skill_name": step.required_skill,
                                "purpose": f"Auto-generated from plan {plan.plan_id} step {idx + 1}: {step.description}",
                                "attach_to_agent": step.agent_name,
                            },
                            agent_name,
                        )
                        # Retry capability check after scaffold/attach.
                        if not _agent_has_skill_or_tool(step.agent_name, step.required_skill):
                            step.status = "failed"
                            step.result = (
                                f"Missing required skill '{step.required_skill}' on agent '{step.agent_name}'. "
                                f"{scaffold_msg}".strip()
                            )
                            if stop_on_error:
                                return f"Execution stopped on step {idx + 1}: {step.result}\n{plan.summary}"
                            continue
                    else:
                        step.status = "failed"
                        step.result = (
                            f"Missing required skill '{step.required_skill}' on agent '{step.agent_name}'. "
                            "auto_scaffold_missing_skills is false."
                        )
                        if stop_on_error:
                            return f"Execution stopped on step {idx + 1}: {step.result}\n{plan.summary}"
                        continue

                try:
                    if step.tool_name:
                        result = await execute_tool(
                            step.tool_name,
                            step.tool_args or {},
                            agent_name=step.agent_name,
                        )
                    else:
                        target = get_agent_by_name(step.agent_name) or get_agent()
                        result = await target.respond(
                            user_message=step.description,
                            channel="plan_execution",
                            user_id=agent_name,
                        )
                    step.result = result
                    step.status = "completed"
                except Exception as e:
                    step.result = f"Execution error: {e}"
                    step.status = "failed"
                    if stop_on_error:
                        return f"Execution stopped on step {idx + 1}: {step.result}\n{plan.summary}"

        completed = sum(1 for s in plan.steps if s.status == "completed")
        failed = sum(1 for s in plan.steps if s.status == "failed")
        details = [
            {
                "step": i + 1,
                "status": s.status,
                "agent": s.agent_name,
                "description": s.description,
                "result": (s.result or "")[:500],
            }
            for i, s in enumerate(plan.steps)
        ]
        return (
            f"Plan {plan.plan_id} execution finished: {completed} completed, {failed} failed.\n"
            f"{json.dumps(details, indent=2)}"
        )

    if name == "scaffold_skill":
        skill_name_raw = args.get("skill_name", "")
        purpose = args.get("purpose", "").strip() or "No purpose provided"
        attach_to_agent = args.get("attach_to_agent", "").strip()
        tools = args.get("tools", [])

        try:
            skill_name = _normalize_skill_name(skill_name_raw)
        except ValueError as e:
            return f"Error: {e}"

        path = _skill_path(skill_name)
        if path.exists():
            outcome = f"Skill scaffold already exists: {path.name}"
        else:
            path.write_text(_build_skill_stub(skill_name, purpose, tools), encoding="utf-8")
            outcome = f"Created skill scaffold: {path.name}"

        if attach_to_agent:
            from chief_of_staff.agent.registry import AGENTS_DIR, get_registry

            registry = get_registry()
            config = registry.get(attach_to_agent)
            if config:
                if skill_name not in config.skills:
                    config.skills.append(skill_name)
                    config.to_yaml(AGENTS_DIR / f"{attach_to_agent}.yaml")
                    outcome += f" | Attached skill '{skill_name}' to agent '{attach_to_agent}'"
            else:
                outcome += f" | Agent '{attach_to_agent}' not found"

        from chief_of_staff.agent.skills import get_skill_registry

        get_skill_registry().reload()
        return outcome

    raise ValueError(f"Unknown orchestration tool: {name}")
