"""Voice transcript command parsing and safe execution gateway."""

from __future__ import annotations

import logging

from chief_of_staff.agent.activity import WEBHOOK_RECEIVED, log_activity
from chief_of_staff.agent.core import get_agent
from chief_of_staff.config import settings

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
    log_activity(
        agent_name="chief_of_staff",
        action_type=WEBHOOK_RECEIVED,
        action_detail="voice.command.detected",
        input_summary=command[:500],
        channel="voice",
        user_id=speaker,
        session_id=session_key,
        metadata={"bot_id": bot_id, "dry_run": settings.voice_exec_dry_run},
    )

    if settings.voice_exec_dry_run:
        return f"[dry-run] Voice command accepted: {command}"

    agent = get_agent()
    result = await agent.respond(
        user_message=command,
        channel="voice",
        user_id=speaker,
        session_id=session_key,
    )
    logger.info("Executed voice command for bot %s speaker %s", bot_id[:8], speaker)
    return result

