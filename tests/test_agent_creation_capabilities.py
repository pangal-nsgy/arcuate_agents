"""Tests for agent creation capability defaults and delegation pass-through."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest


def test_create_agent_defaults_to_full_capability_profile(tmp_path, monkeypatch):
    """create_agent should default to the full skill + permission profile."""
    from chief_of_staff.agent import registry as registry_mod

    monkeypatch.setattr(registry_mod, "AGENTS_DIR", tmp_path)
    reg = registry_mod.AgentRegistry()

    config = reg.create_agent(
        name="ops_bot",
        display_name="Ops Bot",
        system_prompt="You run operations.",
    )

    assert config.skills == registry_mod.DEFAULT_AGENT_SKILLS
    assert config.permissions["can_self_modify"] is True
    assert config.permissions["can_create_agents"] is True
    assert config.permissions["can_send_external"] is True
    assert config.permissions["can_modify_code"] is True
    assert config.permissions["max_delegation_depth"] == 3


@pytest.mark.asyncio
async def test_create_sub_agent_forwards_skills_permissions_and_policy():
    """delegation.create_sub_agent should pass explicit capabilities to registry."""
    from chief_of_staff.agent.skills.delegation import execute

    caller_cfg = SimpleNamespace(permissions={"can_create_agents": True})
    created = SimpleNamespace(
        name="ops_bot",
        display_name="Ops Bot",
        skills=["code_ops", "orchestration"],
        tools=[],
        permissions={"can_modify_code": True},
    )
    captured: dict[str, object] = {}

    def _create_agent(**kwargs):
        captured.update(kwargs)
        return created

    fake_registry = SimpleNamespace(get=lambda _name: caller_cfg, create_agent=_create_agent)

    with (
        patch("chief_of_staff.agent.registry.get_registry", return_value=fake_registry),
        patch("chief_of_staff.agent.activity.log_activity"),
    ):
        result = await execute(
            "create_sub_agent",
            {
                "name": "ops_bot",
                "display_name": "Ops Bot",
                "system_prompt": "Do ops.",
                "skills": ["code_ops", "orchestration"],
                "permissions": {"can_modify_code": True, "can_create_agents": True},
                "tool_policy": {"deny": ["deploy_changes"]},
            },
            "chief_of_staff",
        )

    assert "created" in result.lower()
    assert "permissions" in result.lower()
    assert captured["skills"] == ["code_ops", "orchestration"]
    assert captured["permissions"] == {"can_modify_code": True, "can_create_agents": True}
    assert captured["tool_policy"] == {"deny": ["deploy_changes"]}
