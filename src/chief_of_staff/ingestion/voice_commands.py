"""Voice transcript command parsing and safe execution gateway."""

from __future__ import annotations

import logging

from chief_of_staff.agent.activity import WEBHOOK_RECEIVED, log_activity
from chief_of_staff.agent.core import get_agent
from chief_of_staff.config import settings
from chief_of_staff.gateway.exec_approvals import get_exec_approvals_service

logger = logging.getLogger(__name__)


def extract_voice_command(text: str) -> str:
    """Extract executable command content from a transcript line, if prefixed."""
    value = (text or "").strip()
    if not value:
        return ""
    lower = value.lower()
    for prefix in settings.voice_command_prefixes:
        p = prefix.strip().lower()
        if p and lower.startswith(p):
            return value[len(prefix) :].strip()
    return ""


def _speaker_allowed(speaker: str) -> bool:
    allow = [s.strip().lower() for s in settings.voice_allowed_speakers if s.strip()]
    if not allow:
        return True
    return speaker.strip().lower() in set(allow)


async def handle_transcript_command(bot_id: str, speaker: str, text: str) -> str:
    """Handle a possible voice command from meeting transcript text."""
    if not settings.voice_exec_enabled:
        return ""
    if not _speaker_allowed(speaker):
        return ""

    command = extract_voice_command(text)
    if not command:
        return ""

    session_key = f"hook:voice:{bot_id}"
    requested_by = f"voice:{speaker}:{bot_id}"
    approvals = get_exec_approvals_service()
    request = approvals.request_approval(
        {
            "request": {
                "tool": "voice.command",
                "command": command,
                "requestedBy": requested_by,
                "reason": "voice transcript command",
                "metadata": {"bot_id": bot_id, "speaker": speaker},
            }
        }
    )
    request_id = str(request["requestId"])
    log_activity(
        agent_name="chief_of_staff",
        action_type=WEBHOOK_RECEIVED,
        action_detail="voice.command.detected",
        input_summary=command[:500],
        channel="voice",
        user_id=speaker,
        session_id=session_key,
        metadata={"bot_id": bot_id, "dry_run": settings.voice_exec_dry_run, "approval_id": request_id},
    )

    if settings.voice_exec_dry_run:
        return f"[dry-run] Voice command queued for approval id={request_id}: {command}"

    decision = approvals.wait_decision({"requestId": request_id, "timeoutMs": settings.voice_approval_wait_ms})
    status = str(decision.get("status", "pending"))
    if status == "pending":
        return f"Approval required (id={request_id}) for voice command: {command}"
    if status == "denied":
        return f"Voice command denied (id={request_id})."

    agent = get_agent()
    result = await agent.respond(
        user_message=command,
        channel="voice",
        user_id=speaker,
        session_id=session_key,
    )
    logger.info("Executed voice command for bot %s speaker %s approval %s", bot_id[:8], speaker, request_id)
    return f"Voice command executed (id={request_id}): {result}"
