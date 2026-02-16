"""Tests for OpenClaw-inspired agent control policies."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from chief_of_staff.agent.registry import AgentConfig
from chief_of_staff.agent.skills.delegation import execute as delegation_execute
from chief_of_staff.agent.delegation_context import enter_delegation, exit_delegation


def test_tool_policy_allow_and_deny_wildcards():
    """Allowlist + denylist patterns should be applied with deny precedence."""
    config = AgentConfig(
        name="policy_test",
        tools=["send_email", "send_sms", "search_knowledge"],
        tool_policy={"allow": ["send_*"], "deny": ["*sms"]},
    )
    assert config.get_resolved_tools() == ["send_email"]


def test_tool_policy_deny_all_wins():
    """Wildcard deny-all should remove every tool."""
    config = AgentConfig(
        name="policy_test",
        tools=["send_email", "search_knowledge"],
        tool_policy={"allow": ["*"], "deny": ["*"]},
    )
    assert config.get_resolved_tools() == []


def test_tool_policy_applies_to_resolved_skills():
    """Policy filtering should run after skill/tool resolution."""
    config = AgentConfig(
        name="policy_test",
        skills=["communication"],
        tool_policy={"allow": ["send_*"], "deny": ["send_sms"]},
    )
    fake_registry = SimpleNamespace(resolve_skills=lambda refs: ["send_sms", "send_email", "draft_document"])
    with patch("chief_of_staff.agent.skills.get_skill_registry", return_value=fake_registry):
        assert config.get_resolved_tools() == ["send_email"]


@pytest.mark.asyncio
async def test_delegate_task_respects_max_depth():
    """delegate_task should refuse calls once max_delegation_depth is reached."""
    caller_config = AgentConfig(
        name="chief_of_staff",
        permissions={"max_delegation_depth": 1},
    )
    fake_registry = SimpleNamespace(get=lambda name: caller_config)
    token = enter_delegation()
    try:
        with (
            patch("chief_of_staff.agent.registry.get_registry", return_value=fake_registry),
            patch("chief_of_staff.agent.core.get_agent_by_name", return_value=None),
        ):
            result = await delegation_execute(
                "delegate_task",
                {"agent_name": "onboarding", "task": "Handle onboarding follow-up"},
                "chief_of_staff",
            )
    finally:
        exit_delegation(token)

    assert "max delegation depth reached" in result.lower()


@pytest.mark.asyncio
async def test_delegate_task_within_depth_calls_sub_agent():
    """delegate_task should run when current depth is below max."""
    caller_config = AgentConfig(
        name="chief_of_staff",
        permissions={"max_delegation_depth": 2},
    )
    fake_registry = SimpleNamespace(get=lambda name: caller_config)
    sub_agent = SimpleNamespace(respond=AsyncMock(return_value="done"))

    with (
        patch("chief_of_staff.agent.registry.get_registry", return_value=fake_registry),
        patch("chief_of_staff.agent.core.get_agent_by_name", return_value=sub_agent),
    ):
        result = await delegation_execute(
            "delegate_task",
            {"agent_name": "onboarding", "task": "Handle onboarding follow-up"},
            "chief_of_staff",
        )

    assert "[onboarding response]" in result
    assert "done" in result
