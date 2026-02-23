"""OpenAI-compatible HTTP endpoints backed by the local agent runtime."""

from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from chief_of_staff.agent.core import get_agent
from chief_of_staff.agent.rails import get_rails
from chief_of_staff.config import settings
from chief_of_staff.gateway.auth import require_gateway_token

router = APIRouter(tags=["gateway-openai"])


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return "\n".join(parts)
    return ""


def _messages_to_prompt(payload: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail="messages array is required")

    history: list[dict[str, str]] = []
    last_user = ""
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "")).strip() or "user"
        text = _extract_text(msg.get("content")).strip()
        if not text:
            continue
        if role == "user":
            last_user = text
        history.append({"role": role, "content": text})
    if not last_user:
        raise HTTPException(status_code=400, detail="at least one user message is required")
    return last_user, history[:-1]


async def _run_model(user_message: str, history: list[dict[str, str]], session_key: str) -> str:
    rails = get_rails()
    if not rails.llm_enabled:
        raise HTTPException(status_code=403, detail="LLM inbound is paused by runtime rails")
    agent = get_agent()
    return await agent.respond(
        user_message=user_message,
        conversation_history=history,
        channel="openai_compat",
        user_id="openai_compat",
        session_id=session_key,
    )


@router.post("/v1/chat/completions")
async def openai_chat_completions(request: Request) -> dict[str, Any]:
    require_gateway_token(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON object body is required")

    user_message, history = _messages_to_prompt(payload)
    model = str(payload.get("model", settings.openai_model)).strip() or settings.openai_model
    session_key = str(payload.get("session", "openai:chat")).strip() or "openai:chat"
    response_text = await _run_model(user_message=user_message, history=history, session_key=session_key)
    created = int(time.time())
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": response_text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@router.post("/v1/responses")
async def openai_responses(request: Request) -> dict[str, Any]:
    require_gateway_token(request)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON object body is required")

    model = str(payload.get("model", settings.openai_model)).strip() or settings.openai_model
    session_key = str(payload.get("session", "openai:responses")).strip() or "openai:responses"
    user_message = ""
    history: list[dict[str, str]] = []

    if "messages" in payload:
        user_message, history = _messages_to_prompt(payload)
    else:
        user_message = _extract_text(payload.get("input")).strip()
        if not user_message:
            raise HTTPException(status_code=400, detail="input or messages is required")

    response_text = await _run_model(user_message=user_message, history=history, session_key=session_key)
    created = int(time.time())
    response_id = f"resp_{uuid.uuid4().hex}"
    output_id = f"msg_{uuid.uuid4().hex}"
    return {
        "id": response_id,
        "object": "response",
        "created_at": created,
        "status": "completed",
        "model": model,
        "output": [
            {
                "id": output_id,
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": response_text}],
            }
        ],
    }
