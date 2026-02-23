"""Tests for OpenClaw-style hooks and tools/invoke HTTP routers."""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from chief_of_staff.gateway.hooks import router as hooks_router
from chief_of_staff.gateway.tools_invoke import router as tools_router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(hooks_router)
    app.include_router(tools_router)
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

