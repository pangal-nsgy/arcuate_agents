"""Tests for OpenClaw-style hooks and tools/invoke HTTP routers."""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from chief_of_staff.gateway.hooks import router as hooks_router
from chief_of_staff.gateway.exec_approvals import reset_exec_approvals_service_for_tests
from chief_of_staff.gateway.openai_compat import router as openai_compat_router
from chief_of_staff.gateway.tools_invoke import router as tools_router
from chief_of_staff.gateway.usage_budget import reset_usage_budget_service_for_tests


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(hooks_router)
    app.include_router(tools_router)
    app.include_router(openai_compat_router)
    return app


def test_hooks_reject_query_token(monkeypatch):
    monkeypatch.setattr("chief_of_staff.gateway.hooks.settings.hooks_enabled", True)
    monkeypatch.setattr("chief_of_staff.gateway.hooks.settings.hooks_token", "secret")
    client = TestClient(_build_app())

    resp = client.post("/hooks/wake?token=abc", json={"text": "hello"})
    assert resp.status_code == 400


def test_hooks_agent_accepts_with_bearer_and_returns_run_id(monkeypatch):
    monkeypatch.setattr("chief_of_staff.gateway.hooks.settings.hooks_enabled", True)
    monkeypatch.setattr("chief_of_staff.gateway.hooks.settings.hooks_token", "secret")
    monkeypatch.setattr(
        "chief_of_staff.gateway.hooks.settings.hooks_allow_request_session_key",
        False,
    )
    mock_run = AsyncMock(return_value=None)
    monkeypatch.setattr("chief_of_staff.gateway.hooks._run_agent_hook", mock_run)
    client = TestClient(_build_app())

    resp = client.post(
        "/hooks/agent",
        json={"message": "run this"},
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["status"] == "accepted"
    assert body["runId"]


def test_hooks_reject_session_key_override_by_default(monkeypatch):
    monkeypatch.setattr("chief_of_staff.gateway.hooks.settings.hooks_enabled", True)
    monkeypatch.setattr("chief_of_staff.gateway.hooks.settings.hooks_token", "secret")
    monkeypatch.setattr(
        "chief_of_staff.gateway.hooks.settings.hooks_allow_request_session_key",
        False,
    )
    client = TestClient(_build_app())

    resp = client.post(
        "/hooks/agent",
        json={"message": "run", "sessionKey": "hook:custom"},
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 400


def test_hooks_mapped_wake_renders_template(monkeypatch):
    monkeypatch.setattr("chief_of_staff.gateway.hooks.settings.hooks_enabled", True)
    monkeypatch.setattr("chief_of_staff.gateway.hooks.settings.hooks_token", "secret")
    monkeypatch.setattr(
        "chief_of_staff.gateway.hooks.settings.hooks_mappings",
        [
            {
                "id": "gmail-wake",
                "match": {"path": "gmail", "source": "gmail"},
                "action": "wake",
                "wakeMode": "now",
                "textTemplate": "Mail from {{payload.from}} re {{payload.subject}}",
            }
        ],
    )
    client = TestClient(_build_app())

    resp = client.post(
        "/hooks/gmail",
        json={"source": "gmail", "from": "Ada", "subject": "Roadmap"},
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["mappingId"] == "gmail-wake"
    assert body["action"] == "wake"
    assert body["mode"] == "now"


def test_hooks_mapped_agent_accepts_and_returns_run_id(monkeypatch):
    monkeypatch.setattr("chief_of_staff.gateway.hooks.settings.hooks_enabled", True)
    monkeypatch.setattr("chief_of_staff.gateway.hooks.settings.hooks_token", "secret")
    monkeypatch.setattr(
        "chief_of_staff.gateway.hooks.settings.hooks_allow_request_session_key",
        False,
    )
    monkeypatch.setattr(
        "chief_of_staff.gateway.hooks.settings.hooks_allowed_session_key_prefixes",
        ["hook:"],
    )
    monkeypatch.setattr(
        "chief_of_staff.gateway.hooks.settings.hooks_mappings",
        [
            {
                "id": "task-agent",
                "match": {"path": "tasks"},
                "action": "agent",
                "wakeMode": "now",
                "name": "Tasks",
                "messageTemplate": "Execute {{payload.task}}",
                "sessionKey": "hook:tasks:{{payload.id}}",
            }
        ],
    )
    mock_run = AsyncMock(return_value=None)
    monkeypatch.setattr("chief_of_staff.gateway.hooks._run_agent_hook", mock_run)
    client = TestClient(_build_app())

    resp = client.post(
        "/hooks/tasks",
        json={"id": "42", "task": "inbox-zero"},
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["mappingId"] == "task-agent"
    assert body["action"] == "agent"
    assert body["status"] == "accepted"
    assert body["runId"]


def test_tools_invoke_denies_default_blocked_tool(monkeypatch):
    monkeypatch.setattr("chief_of_staff.gateway.tools_invoke.settings.gateway_auth_token", "gw")
    monkeypatch.setattr(
        "chief_of_staff.gateway.tools_invoke.settings.gateway_tools_deny",
        ["sessions_spawn"],
    )
    monkeypatch.setattr(
        "chief_of_staff.gateway.tools_invoke.settings.gateway_tools_allow",
        [],
    )
    monkeypatch.setattr(
        "chief_of_staff.gateway.tools_invoke.ALL_TOOL_DEFINITIONS",
        {"sessions_spawn": {"name": "sessions_spawn"}},
    )
    client = TestClient(_build_app())

    resp = client.post(
        "/tools/invoke",
        json={"tool": "sessions_spawn", "args": {}},
        headers={"Authorization": "Bearer gw"},
    )
    assert resp.status_code == 404


def test_tools_invoke_runs_tool_when_allowed(monkeypatch):
    monkeypatch.setattr("chief_of_staff.gateway.tools_invoke.settings.gateway_auth_token", "gw")
    monkeypatch.setattr(
        "chief_of_staff.gateway.tools_invoke.settings.gateway_tools_deny",
        ["sessions_spawn"],
    )
    monkeypatch.setattr(
        "chief_of_staff.gateway.tools_invoke.settings.gateway_tools_allow",
        ["sessions_spawn"],
    )
    monkeypatch.setattr(
        "chief_of_staff.gateway.tools_invoke.ALL_TOOL_DEFINITIONS",
        {"sessions_spawn": {"name": "sessions_spawn"}},
    )
    mock_exec = AsyncMock(return_value="ok")
    monkeypatch.setattr("chief_of_staff.gateway.tools_invoke.execute_tool", mock_exec)
    client = TestClient(_build_app())

    resp = client.post(
        "/tools/invoke",
        json={"tool": "sessions_spawn", "args": {}},
        headers={"Authorization": "Bearer gw"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["result"] == "ok"


def test_exec_approvals_get_set_persist(tmp_path, monkeypatch):
    approvals_path = tmp_path / "exec-approvals.json"
    monkeypatch.setattr("chief_of_staff.gateway.tools_invoke.settings.gateway_auth_token", "gw")
    monkeypatch.setattr(
        "chief_of_staff.gateway.exec_approvals.settings.exec_approvals_path",
        str(approvals_path),
    )
    reset_exec_approvals_service_for_tests()
    client = TestClient(_build_app())

    get_resp = client.post(
        "/tools/invoke",
        json={"action": "exec.approvals.get", "args": {}},
        headers={"Authorization": "Bearer gw"},
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["result"]["policy"]["requireApprovalByDefault"] is True

    set_resp = client.post(
        "/tools/invoke",
        json={
            "action": "exec.approvals.set",
            "args": {
                "policy": {
                    "requireApprovalByDefault": False,
                    "allowCommandPrefixes": ["git status", "ls"],
                    "denyCommandPrefixes": ["rm -rf"],
                }
            },
        },
        headers={"Authorization": "Bearer gw"},
    )
    assert set_resp.status_code == 200
    assert set_resp.json()["result"]["policy"]["requireApprovalByDefault"] is False
    assert approvals_path.exists()

    # Recreate service and verify persisted values are loaded.
    reset_exec_approvals_service_for_tests()
    get_again = client.post(
        "/tools/invoke",
        json={"action": "exec.approvals.get", "args": {}},
        headers={"Authorization": "Bearer gw"},
    )
    assert get_again.status_code == 200
    assert get_again.json()["result"]["policy"]["allowCommandPrefixes"] == ["git status", "ls"]


def test_exec_approval_request_wait_and_resolve(tmp_path, monkeypatch):
    approvals_path = tmp_path / "exec-approvals.json"
    monkeypatch.setattr("chief_of_staff.gateway.tools_invoke.settings.gateway_auth_token", "gw")
    monkeypatch.setattr(
        "chief_of_staff.gateway.exec_approvals.settings.exec_approvals_path",
        str(approvals_path),
    )
    reset_exec_approvals_service_for_tests()
    client = TestClient(_build_app())

    request_resp = client.post(
        "/tools/invoke",
        json={
            "action": "exec.approval.request",
            "args": {
                "request": {
                    "tool": "execute_python",
                    "command": "print('hi')",
                    "requestedBy": "agent:chief_of_staff",
                    "reason": "need to inspect output",
                }
            },
        },
        headers={"Authorization": "Bearer gw"},
    )
    assert request_resp.status_code == 200
    request_id = request_resp.json()["result"]["requestId"]
    assert request_id
    assert request_resp.json()["result"]["status"] == "pending"

    pending_resp = client.post(
        "/tools/invoke",
        json={
            "action": "exec.approval.waitDecision",
            "args": {"requestId": request_id, "timeoutMs": 1},
        },
        headers={"Authorization": "Bearer gw"},
    )
    assert pending_resp.status_code == 200
    assert pending_resp.json()["result"]["status"] == "pending"

    resolve_resp = client.post(
        "/tools/invoke",
        json={
            "action": "exec.approval.resolve",
            "args": {"requestId": request_id, "decision": "approved", "decidedBy": "owner"},
        },
        headers={"Authorization": "Bearer gw"},
    )
    assert resolve_resp.status_code == 200
    assert resolve_resp.json()["result"]["status"] == "approved"

    decided_resp = client.post(
        "/tools/invoke",
        json={
            "action": "exec.approval.waitDecision",
            "args": {"requestId": request_id, "timeoutMs": 1},
        },
        headers={"Authorization": "Bearer gw"},
    )
    assert decided_resp.status_code == 200
    assert decided_resp.json()["result"]["status"] == "approved"


def test_usage_actions_and_budget_stop(tmp_path, monkeypatch):
    usage_path = tmp_path / "usage-ledger.json"
    monkeypatch.setattr("chief_of_staff.gateway.tools_invoke.settings.gateway_auth_token", "gw")
    monkeypatch.setattr(
        "chief_of_staff.gateway.usage_budget.settings.usage_ledger_path",
        str(usage_path),
    )
    monkeypatch.setattr(
        "chief_of_staff.gateway.usage_budget.settings.usage_run_budget_usd",
        1.0,
    )
    monkeypatch.setattr(
        "chief_of_staff.gateway.usage_budget.settings.usage_session_budget_usd",
        0.015,
    )
    monkeypatch.setattr(
        "chief_of_staff.gateway.usage_budget.settings.usage_day_budget_usd",
        10.0,
    )
    monkeypatch.setattr(
        "chief_of_staff.gateway.tools_invoke.settings.usage_default_action_cost_usd",
        0.01,
    )
    monkeypatch.setattr(
        "chief_of_staff.gateway.tools_invoke.ALL_TOOL_DEFINITIONS",
        {"sessions_spawn": {"name": "sessions_spawn"}},
    )
    monkeypatch.setattr(
        "chief_of_staff.gateway.tools_invoke.settings.gateway_tools_allow",
        ["sessions_spawn"],
    )
    monkeypatch.setattr(
        "chief_of_staff.gateway.tools_invoke.settings.gateway_tools_deny",
        [],
    )
    mock_exec = AsyncMock(return_value="ok")
    monkeypatch.setattr("chief_of_staff.gateway.tools_invoke.execute_tool", mock_exec)
    reset_usage_budget_service_for_tests()
    client = TestClient(_build_app())

    status_resp = client.post(
        "/tools/invoke",
        json={"action": "usage.status", "sessionKey": "s1", "runId": "r1", "args": {}},
        headers={"Authorization": "Bearer gw"},
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["result"]["spentUsd"]["session"] == 0.0

    first = client.post(
        "/tools/invoke",
        json={"tool": "sessions_spawn", "args": {}, "sessionKey": "s1", "runId": "r1"},
        headers={"Authorization": "Bearer gw"},
    )
    assert first.status_code == 200

    second = client.post(
        "/tools/invoke",
        json={"tool": "sessions_spawn", "args": {}, "sessionKey": "s1", "runId": "r2"},
        headers={"Authorization": "Bearer gw"},
    )
    assert second.status_code == 429
    assert "budget exceeded" in second.json()["detail"]

    cost_resp = client.post(
        "/tools/invoke",
        json={"action": "usage.cost", "args": {}},
        headers={"Authorization": "Bearer gw"},
    )
    assert cost_resp.status_code == 200
    assert cost_resp.json()["result"]["daySpentUsd"] == 0.01


def test_openai_chat_completions_compat(monkeypatch):
    monkeypatch.setattr(
        "chief_of_staff.gateway.openai_compat.settings.gateway_auth_token",
        "gw",
    )
    monkeypatch.setattr(
        "chief_of_staff.gateway.openai_compat.get_rails",
        lambda: type("R", (), {"llm_enabled": True})(),
    )
    mock_agent = type("Agent", (), {"respond": AsyncMock(return_value="hello from agent")})()
    monkeypatch.setattr("chief_of_staff.gateway.openai_compat.get_agent", lambda: mock_agent)
    client = TestClient(_build_app())

    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4.1",
            "messages": [{"role": "user", "content": "say hi"}],
        },
        headers={"Authorization": "Bearer gw"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "hello from agent"


def test_openai_responses_compat(monkeypatch):
    monkeypatch.setattr(
        "chief_of_staff.gateway.openai_compat.settings.gateway_auth_token",
        "gw",
    )
    monkeypatch.setattr(
        "chief_of_staff.gateway.openai_compat.get_rails",
        lambda: type("R", (), {"llm_enabled": True})(),
    )
    mock_agent = type("Agent", (), {"respond": AsyncMock(return_value="done")})()
    monkeypatch.setattr("chief_of_staff.gateway.openai_compat.get_agent", lambda: mock_agent)
    client = TestClient(_build_app())

    resp = client.post(
        "/v1/responses",
        json={"model": "gpt-4.1", "input": "status"},
        headers={"Authorization": "Bearer gw"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "response"
    assert body["output"][0]["content"][0]["text"] == "done"
