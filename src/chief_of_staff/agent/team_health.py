"""Team health monitoring — weekly pulse, engagement alerts, catch-up summaries."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


async def generate_weekly_pulse() -> str:
    """Generate a weekly team health pulse report.

    Gathers activity data for each founder and calls the agent
    to produce a formatted analysis.
    """
    from chief_of_staff.agent.core import Agent
    from chief_of_staff.agent.registry import get_registry
    from chief_of_staff.agent.activity import get_recent_activity
    from chief_of_staff.config import settings

    # Gather raw activity stats for the last 7 days
    recent = get_recent_activity(limit=500, since_hours=168)

    # Group activity by user_id (founder)
    founder_stats: dict[str, dict[str, int]] = {}
    for entry in recent:
        uid = entry.get("user_id", "")
        if not uid:
            continue
        if uid not in founder_stats:
            founder_stats[uid] = {"total": 0, "messages": 0, "emails": 0, "tools": 0}
        founder_stats[uid]["total"] += 1
        action = entry.get("action_type", "")
        if action in ("message_received", "message_sent"):
            founder_stats[uid]["messages"] += 1
        elif action in ("email_received", "email_sent"):
            founder_stats[uid]["emails"] += 1
        elif action == "tool_use":
            founder_stats[uid]["tools"] += 1

    # Build context for agent
    stats_summary = "Weekly activity by person:\n"
    if founder_stats:
        for uid, stats in sorted(founder_stats.items(), key=lambda x: x[1]["total"], reverse=True):
            stats_summary += f"- {uid}: {stats['total']} actions ({stats['messages']} messages, {stats['emails']} emails)\n"
    else:
        stats_summary += "- No user-attributed activity found this week.\n"

    stats_summary += f"\nTotal activity entries in last 7 days: {len(recent)}\n"
    stats_summary += f"Configured founder emails: {', '.join(settings.founder_emails) if settings.founder_emails else 'none'}\n"

    config = get_registry().get("chief_of_staff")
    if not config:
        logger.error("Cannot generate pulse — chief_of_staff config not found")
        return ""

    agent = Agent(config)
    prompt = (
        "Generate the weekly team health pulse for Arcuate. "
        "Use the data below plus your knowledge tools to build a complete picture.\n\n"
        f"{stats_summary}\n"
        "Include:\n"
        "1. **Activity Summary** — per-person breakdown, who's been active vs quiet\n"
        "2. **Engagement Trend** — any notable changes from what you know\n"
        "3. **Unanswered Items** — search for emails or messages that got no reply\n"
        "4. **Wins** — deals closed, successful calls, milestones\n"
        "5. **Concerns** — anything that looks off (stalled leads, dropped balls)\n"
        "6. **Team Energy** — overall read on how the team is doing\n\n"
        "Be direct and specific. This goes to the founders."
    )

    try:
        result = await agent.respond(
            user_message=prompt,
            channel="scheduler",
            user_id="weekly_pulse",
        )
        return result or ""
    except Exception as e:
        logger.error(f"Weekly pulse generation failed: {e}", exc_info=True)
        return ""


async def check_engagement_alerts() -> list[str]:
    """Check for founders who've gone quiet or threads with no response.

    Returns a list of alert messages. Empty list means all is well.
    """
    from chief_of_staff.agent.activity import get_recent_activity
    from chief_of_staff.config import settings

    alerts: list[str] = []

    if not settings.founder_emails:
        return alerts

    # Fetch all recent activity once (avoid N+1 queries per founder)
    all_recent = get_recent_activity(limit=500, since_hours=240)

    for email in settings.founder_emails:
        founder_active = False
        last_seen = None
        for entry in all_recent:
            uid = entry.get("user_id", "")
            if email.lower() in uid.lower():
                founder_active = True
                last_seen = entry.get("timestamp", "")
                break

        if not founder_active:
            alerts.append(
                f"Haven't seen activity from {email} in the last 10 days. Everything ok?"
            )
        elif last_seen:
            try:
                last_dt = datetime.fromisoformat(last_seen)
                days_ago = (datetime.utcnow() - last_dt).days
                if days_ago >= 5:
                    alerts.append(
                        f"{email} was last active {days_ago} days ago. Might be worth a check-in."
                    )
            except ValueError:
                pass

    return alerts


async def generate_catchup(founder_name: str, days: int = 7) -> str:
    """Generate a personalized catch-up summary for a team member.

    Searches the knowledge base for recent activity relevant to this person
    and has the agent create a focused summary.
    """
    from chief_of_staff.agent.core import Agent
    from chief_of_staff.agent.registry import get_registry
    from chief_of_staff.agent.activity import log_activity, CATCHUP_GENERATED

    config = get_registry().get("chief_of_staff")
    if not config:
        logger.error("Cannot generate catch-up — chief_of_staff config not found")
        return ""

    agent = Agent(config)
    prompt = (
        f"Generate a catch-up summary for {founder_name} covering the last {days} days.\n\n"
        f"Search the knowledge base for:\n"
        f"- Recent emails and threads\n"
        f"- Meeting transcripts and notes\n"
        f"- ElevenLabs call outcomes\n"
        f"- Any decisions or action items that involve {founder_name}\n\n"
        f"Format as a quick-scan briefing:\n"
        f"1. **Decisions made** while they were away\n"
        f"2. **Action items** assigned to them\n"
        f"3. **Key updates** they should know about\n"
        f"4. **Threads** they were tagged in or should weigh in on\n\n"
        f"Keep it focused — only include things relevant to {founder_name}'s role."
    )

    try:
        result = await agent.respond(
            user_message=prompt,
            channel="scheduler",
            user_id=f"catchup_{founder_name}",
        )
        log_activity(
            agent_name="chief_of_staff",
            action_type=CATCHUP_GENERATED,
            action_detail=f"Catch-up for {founder_name} ({days}d)",
            channel="scheduler",
            user_id=founder_name,
        )
        return result or ""
    except Exception as e:
        logger.error(f"Catch-up generation failed for {founder_name}: {e}", exc_info=True)
        return ""
