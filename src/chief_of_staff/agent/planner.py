"""Task planner — breaks down complex requests into executable steps.

Used by the agent core when a request requires multiple tool calls
or multi-step reasoning (e.g., "create onboarding packet for Dr. Smith").
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TaskStep:
    """A single step in a task plan."""

    description: str
    agent_name: str = "chief_of_staff"
    required_skill: str = ""
    tool_name: str | None = None
    tool_args: dict | None = None
    depends_on: list[int] = field(default_factory=list)
    result: str | None = None
    status: str = "pending"  # pending, running, completed, failed


@dataclass
class TaskPlan:
    """A multi-step plan for accomplishing a complex request."""

    goal: str
    plan_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    steps: list[TaskStep] = field(default_factory=list)

    def add_step(
        self,
        description: str,
        agent_name: str = "chief_of_staff",
        required_skill: str = "",
        tool_name: str | None = None,
        tool_args: dict | None = None,
        depends_on: list[int] | None = None,
    ) -> int:
        """Add a step to the plan. Returns the step index."""
        step = TaskStep(
            description=description,
            agent_name=agent_name,
            required_skill=required_skill,
            tool_name=tool_name,
            tool_args=tool_args,
            depends_on=depends_on or [],
        )
        self.steps.append(step)
        return len(self.steps) - 1

    def get_ready_steps(self) -> list[int]:
        """Get indices of steps that are ready to execute (all dependencies met)."""
        ready = []
        for i, step in enumerate(self.steps):
            if step.status != "pending":
                continue
            deps_met = all(
                self.steps[d].status == "completed" for d in step.depends_on
            )
            if deps_met:
                ready.append(i)
        return ready

    @property
    def is_complete(self) -> bool:
        return all(s.status in ("completed", "failed") for s in self.steps)

    @property
    def summary(self) -> str:
        lines = [f"Plan {self.plan_id[:8]}: {self.goal}"]
        for i, step in enumerate(self.steps):
            status_icon = {"pending": " ", "running": ">", "completed": "x", "failed": "!"}
            tool_hint = f" [{step.tool_name}]" if step.tool_name else ""
            skill_hint = f" (needs skill: {step.required_skill})" if step.required_skill else ""
            lines.append(
                f"  [{status_icon.get(step.status, '?')}] {i+1}. "
                f"{step.description} -> {step.agent_name}{tool_hint}{skill_hint}"
            )
        return "\n".join(lines)
