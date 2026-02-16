"""Proactive briefing generators — daily briefing, meeting debriefs."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


async def generate_daily_briefing() -> str:
    """Generate the morning briefing for the Arcuate team.

    Calls agent.respond() with a structured prompt that triggers
    the agent to use its knowledge tools to gather real data.
    """
    from chief_of_staff.agent.core import Agent
    from chief_of_staff.agent.registry import get_registry

    config = get_registry().get("chief_of_staff")
    if not config:
        logger.error("Cannot generate briefing — chief_of_staff config not found")
        return ""

    agent = Agent(config)
    prompt = (
        "Generate today's morning briefing for the Arcuate team. "
        "Use your search tools to gather real data. Include:\n"
        "1. New emails received in the last 24 hours that need attention\n"
        "2. ElevenLabs call activity (search for recent call transcripts)\n"
        "3. Any open complaints\n"
        "4. Follow-ups that are overdue or stalled\n"
        "5. Key metrics summary\n\n"
        "Format as concise bullet points, most urgent first. "
        "Use bold headers for each section."
    )

    try:
        result = await agent.respond(
            user_message=prompt,
            channel="scheduler",
            user_id="daily_briefing",
        )
        return result or ""
    except Exception as e:
        logger.error(f"Daily briefing generation failed: {e}", exc_info=True)
        return ""


async def generate_meeting_debrief(title: str, transcript: str) -> tuple[str, bool]:
    """Generate meeting feedback and determine if it should be emailed.

    Returns (feedback_text, is_important).
    """
    from chief_of_staff.agent.core import Agent
    from chief_of_staff.agent.registry import get_registry

    config = get_registry().get("chief_of_staff")
    if not config:
        logger.error("Cannot generate debrief — chief_of_staff config not found")
        return "", False

    agent = Agent(config)
    # Truncate transcript to fit in context
    truncated = transcript[:8000]
    prompt = (
        f"Analyze this meeting and provide feedback for the Arcuate team.\n\n"
        f"**Meeting**: {title}\n\n"
        f"Provide:\n"
        f"1. **TL;DR** (2-3 sentences)\n"
        f"2. **Key decisions** made\n"
        f"3. **Action items** (who does what by when)\n"
        f"4. **What went well**\n"
        f"5. **What could improve** (be direct — keep us sharp)\n"
        f"6. For sales/outreach calls: objection analysis, likelihood to close, recommended next steps\n"
        f"7. At the very end, on its own line, write exactly: IMPORTANT: YES or IMPORTANT: NO\n"
        f"   (YES if: new client meeting, significant deal discussed, escalation needed, bad news)\n\n"
        f"**Transcript**:\n{truncated}"
    )

    try:
        result = await agent.respond(
            user_message=prompt,
            channel="scheduler",
            user_id="meeting_debrief",
        )
        if not result:
            return "", False

        is_important = bool(re.search(r"IMPORTANT:\s*YES", result, re.IGNORECASE))
        return result, is_important
    except Exception as e:
        logger.error(f"Meeting debrief generation failed: {e}", exc_info=True)
        return "", False


async def post_meeting_debrief(title: str, feedback: str, is_important: bool) -> None:
    """Post meeting debrief to Discord and optionally email founders."""
    from chief_of_staff.communication.discord_bot import send_to_channel
    from chief_of_staff.config import settings
    from chief_of_staff.agent.activity import log_activity, MEETING_DEBRIEF

    if not feedback:
        return

    # Always post to Discord
    discord_msg = f"**Meeting Debrief: {title}**\n\n{feedback}"
    await send_to_channel(settings.meeting_notes_channel, discord_msg)

    # Email founders if important
    if is_important and settings.founder_emails:
        try:
            from chief_of_staff.communication.email import send_email

            tldr = _extract_tldr(feedback)
            email_body = tldr if tldr else feedback[:2000]
            for email_addr in settings.founder_emails:
                await send_email(
                    to=email_addr,
                    subject=f"Meeting Summary: {title}",
                    body=email_body,
                )
        except Exception as e:
            logger.error(f"Failed to email meeting debrief: {e}")

    log_activity(
        agent_name="chief_of_staff",
        action_type=MEETING_DEBRIEF,
        action_detail=f"Debrief: {title}",
        channel="scheduler",
        metadata={"title": title, "is_important": is_important},
    )


def _extract_tldr(feedback: str) -> str:
    """Extract the TL;DR section from meeting feedback."""
    # Look for TL;DR section
    match = re.search(
        r"\*?\*?TL;?DR\*?\*?[:\s]*(.+?)(?=\n\*?\*?[A-Z]|\n##|\n\d+\.|\Z)",
        feedback,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        return match.group(1).strip()
    # Fallback: first paragraph
    paragraphs = feedback.strip().split("\n\n")
    return paragraphs[0] if paragraphs else feedback[:500]
