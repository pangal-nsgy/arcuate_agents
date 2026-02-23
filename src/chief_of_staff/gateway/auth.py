"""Gateway HTTP auth helpers."""

from __future__ import annotations

from fastapi import HTTPException, Request

from chief_of_staff.config import settings


def extract_bearer_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def require_gateway_token(request: Request) -> None:
    expected = settings.gateway_auth_token
    if not expected:
        raise HTTPException(status_code=401, detail="Gateway auth token is not configured")

    token = extract_bearer_token(request)
    if token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

