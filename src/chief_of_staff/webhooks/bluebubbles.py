"""BlueBubbles webhook handlers for inbound iMessage events."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Request

from chief_of_staff.agent.activity import ERROR, SMS_RECEIVED, SMS_SENT, log_activity
from chief_of_staff.agent.core import get_agent
from chief_of_staff.agent.rails import get_rails
from chief_of_staff.communication.bluebubbles import send_bluebubbles_text
from chief_of_staff.communication.bluebubbles_pairing import get_bluebubbles_pairing_store
from chief_of_staff.communication.control_commands import handle_control_message
from chief_of_staff.config import settings
from chief_of_staff.knowledge.database import get_recent_conversations, log_conversation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/bluebubbles", tags=["bluebubbles"])


def _extract_inbound(payload: dict[str, Any]) -> tuple[str, str, str]:
    """Best-effort extraction for sender/chat/text across BlueBubbles payload variants."""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    sender = (
        data.get("handle")
        or data.get("sender")
        or data.get("from")
        or data.get("address")
        or ""
    )
    chat_guid = (
        data.get("chatGuid")
        or data.get("chat_guid")
        or data.get("guid")
        or data.get("conversationId")
        or ""
    )
    text = (
        data.get("text")
        or data.get("message")
        or data.get("body")
        or ""
    )
    return str(sender).strip(), str(chat_guid).strip(), str(text).strip()


def _extract_group_metadata(payload: dict[str, Any]) -> tuple[bool, bool]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    chat_guid = str(
        data.get("chatGuid")
        or data.get("chat_guid")
        or data.get("guid")
        or data.get("conversationId")
        or ""
    ).strip()
    is_group = bool(
        data.get("isGroup")
        or data.get("isGroupChat")
        or data.get("group")
        or (isinstance(data.get("participants"), list) and len(data.get("participants", [])) > 2)
        or chat_guid.startswith("chat")
    )
    mentions_flag = bool(
        data.get("mentionsMe")
        or data.get("mentioned")
        or data.get("isMentioned")
        or (isinstance(data.get("mentions"), list) and len(data.get("mentions", [])) > 0)
    )
    return is_group, mentions_flag


def _has_mention(text: str, payload: dict[str, Any]) -> bool:
    _, mention_flag = _extract_group_metadata(payload)
    if mention_flag:
        return True
    lowered = text.lower()
    keywords = [k.strip().lower() for k in settings.bluebubbles_mention_keywords if k.strip()]
    return any(keyword in lowered for keyword in keywords)


def _normalize_policy(raw: str, allowed: set[str], fallback: str) -> str:
    policy = (raw or "").strip().lower()
    if policy in allowed:
        return policy
    return fallback


def _evaluate_sender_policy(sender: str, text: str, payload: dict[str, Any]) -> tuple[bool, str | None, str | None]:
    """Return (allowed, ignored_reason, reply_text)."""
    sender_key = sender.strip()
    if not sender_key:
        return False, "missing_sender", None

    paired = get_bluebubbles_pairing_store().is_paired(sender_key)
    dm_allow = {s.strip() for s in settings.bluebubbles_allow_from if s.strip()}
    group_allow = {s.strip() for s in settings.bluebubbles_group_allow_from if s.strip()}

    is_group, _ = _extract_group_metadata(payload)
    if is_group:
        group_policy = _normalize_policy(
            settings.bluebubbles_group_policy,
            {"allowlist", "open", "disabled"},
            "allowlist",
        )
        if group_policy == "disabled":
            return False, "group_disabled", None
        if settings.bluebubbles_require_mention_in_groups and not _has_mention(text, payload):
            return False, "group_no_mention", None
        if group_policy == "open":
            return True, None, None
        if sender_key in group_allow or sender_key in dm_allow or paired:
            return True, None, None
        return False, "group_allowlist_miss", None

    dm_policy = _normalize_policy(settings.bluebubbles_dm_policy, {"pairing", "allowlist", "open"}, "pairing")
    if dm_policy == "open":
        return True, None, None
    if dm_policy == "allowlist":
        return (sender_key in dm_allow), ("dm_allowlist_miss" if sender_key not in dm_allow else None), None
    if sender_key in dm_allow or paired:
        return True, None, None
    code = get_bluebubbles_pairing_store().request(sender_key)
    return (
        False,
        "dm_pairing_required",
        (
            "Pairing required before I can respond here. "
            f"Share pairing code {code} with an operator to approve."
        ),
    )


def _is_authorized_webhook(req: Request) -> bool:
    secret = settings.bluebubbles_webhook_secret or settings.bluebubbles_password
    if not secret:
        return False
    supplied = (
        req.headers.get("x-openclaw-token")
        or req.headers.get("x-password")
        or req.headers.get("password")
        or req.query_params.get("password")
    )
    return bool(supplied) and supplied == secret


@router.post("")
async def inbound_bluebubbles(request: Request) -> dict[str, object]:
    """Handle inbound BlueBubbles webhook events."""
    if not settings.bluebubbles_enabled:
        return {"ok": False, "error": "BLUEBUBBLES_ENABLED is false"}

    if not _is_authorized_webhook(request):
        return {"ok": False, "error": "Unauthorized"}

    payload = await request.json()
    sender, chat_guid, text = _extract_inbound(payload)
    if not text or not sender or not chat_guid:
        return {"ok": True, "ignored": "missing sender/chat/text"}

    logger.info("Incoming iMessage from %s in %s: %s", sender, chat_guid, text[:120])

    # Deterministic control commands first (same rail behavior as SMS path).
    control_result = handle_control_message(sender, text)
    if control_result.handled:
        await send_bluebubbles_text(chat_guid=chat_guid, text=control_result.response)
        return {"ok": True, "handled": "control_command"}

    allowed, ignored_reason, reply_text = _evaluate_sender_policy(sender, text, payload)
    if not allowed:
        if reply_text:
            await send_bluebubbles_text(chat_guid=chat_guid, text=reply_text)
            return {"ok": True, "handled": "pairing_required"}
        return {"ok": True, "ignored": ignored_reason or "policy_blocked"}

    log_activity(
        agent_name="chief_of_staff",
        action_type=SMS_RECEIVED,
        action_detail=text[:500],
        channel="imessage_bluebubbles",
        user_id=sender,
        metadata={"chat_guid": chat_guid},
    )

    log_conversation(
        conv_id=str(uuid.uuid4()),
        founder_phone=sender,
        direction="inbound",
        message=text,
    )

    recent = get_recent_conversations(sender, limit=10)
    history = []
    for msg in reversed(recent):
        role = "assistant" if msg.get("direction") == "outbound" else "user"
        history.append({"role": role, "content": msg["message"]})

    rails = get_rails()
    if not rails.llm_enabled:
        response_text = (
            "LLM handling is currently paused for safety. "
            "Send '/resume llm' from an authorized number when ready."
        )
    else:
        try:
            agent = get_agent()
            response_text = await agent.respond(
                user_message=text,
                conversation_history=history[:-1],
                channel="imessage_bluebubbles",
                user_id=sender,
            )
        except Exception as e:
            logger.error("BlueBubbles agent failure: %s", e, exc_info=True)
            log_activity(
                agent_name="chief_of_staff",
                action_type=ERROR,
                action_detail=f"BlueBubbles agent failure: {e}",
                channel="imessage_bluebubbles",
                user_id=sender,
            )
            response_text = "Something went wrong — I'll get back to you."

    log_conversation(
        conv_id=str(uuid.uuid4()),
        founder_phone=sender,
        direction="outbound",
        message=response_text,
    )

    log_activity(
        agent_name="chief_of_staff",
        action_type=SMS_SENT,
        action_detail=response_text[:500],
        channel="imessage_bluebubbles",
        user_id=sender,
        metadata={"chat_guid": chat_guid},
    )

    await send_bluebubbles_text(chat_guid=chat_guid, text=response_text)
    return {"ok": True}
