"""Background scheduler — periodically re-ingests data from all sources."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None

SYNC_INTERVAL_SECONDS = 300  # 5 minutes


async def _renew_gmail_watch() -> None:
    """Renew Gmail push notification watch. Safe to call repeatedly (idempotent)."""
    from chief_of_staff.config import settings
    if not settings.gmail_watch_topic:
        return
    try:
        from chief_of_staff.communication._google_auth import get_gmail_service
        service = get_gmail_service()
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: service.users().watch(
            userId="me",
            body={"topicName": settings.gmail_watch_topic, "labelIds": ["INBOX"]},
        ).execute())
        logger.info(f"Gmail watch renewed, expires: {result.get('expiration')}")
    except Exception as e:
        logger.error(f"Gmail watch renewal failed: {e}")


async def _sync_loop():
    """Runs forever, syncing all sources on an interval."""
    # Wait before first sync to let the server start up
    await asyncio.sleep(60)

    while True:
        try:
            logger.info("=== Scheduled sync starting ===")
            await run_sync()
            await run_scheduled_actions()
        except Exception as e:
            logger.error(f"Sync loop iteration failed: {e}", exc_info=True)
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)


async def run_sync():
    """Run a single sync of all configured sources. Uses threads to avoid blocking."""
    from chief_of_staff.agent.activity import log_activity, EMAIL_INGESTED, DOC_INGESTED, CALL_INGESTED, INGESTION_SYNC, ERROR

    loop = asyncio.get_event_loop()
    results = {}

    # Renew Gmail push notification watch (idempotent, prevents 7-day expiry)
    await _renew_gmail_watch()

    # Emails (sync function — run in thread)
    try:
        from chief_of_staff.ingestion.gmail import fetch_and_ingest_emails
        count = await loop.run_in_executor(
            None, lambda: fetch_and_ingest_emails(max_results=500, newer_than="3d")
        )
        results["emails"] = count
        logger.info(f"Synced {count} emails")
        if count > 0:
            log_activity(
                agent_name="chief_of_staff",
                action_type=EMAIL_INGESTED,
                action_detail=f"Synced {count} emails",
                channel="scheduler",
            )
    except Exception as e:
        logger.error(f"Email sync failed: {e}")
        log_activity(agent_name="chief_of_staff", action_type=ERROR, action_detail=f"Email sync failed: {e}", channel="scheduler")

    # Google Docs (sync function — run in thread)
    try:
        from chief_of_staff.ingestion.gdocs import fetch_and_ingest_docs
        count = await loop.run_in_executor(None, lambda: fetch_and_ingest_docs(max_results=50))
        results["docs"] = count
        logger.info(f"Synced {count} docs")
        if count > 0:
            log_activity(
                agent_name="chief_of_staff",
                action_type=DOC_INGESTED,
                action_detail=f"Synced {count} Google Docs",
                channel="scheduler",
            )
    except Exception as e:
        logger.error(f"Docs sync failed: {e}")
        log_activity(agent_name="chief_of_staff", action_type=ERROR, action_detail=f"Docs sync failed: {e}", channel="scheduler")

    # ElevenLabs (already async)
    try:
        from chief_of_staff.ingestion.elevenlabs import fetch_and_ingest_transcripts
        count = await fetch_and_ingest_transcripts(limit=50)
        results["transcripts"] = count
        logger.info(f"Synced {count} ElevenLabs transcripts")
        if count > 0:
            asyncio.create_task(_debrief_new_calls(count))
    except Exception as e:
        logger.error(f"ElevenLabs sync failed: {e}")
        log_activity(agent_name="chief_of_staff", action_type=ERROR, action_detail=f"ElevenLabs sync failed: {e}", channel="scheduler")

    # Log the sync cycle
    log_activity(
        agent_name="chief_of_staff",
        action_type=INGESTION_SYNC,
        action_detail=f"Sync complete: {results}",
        channel="scheduler",
        metadata=results,
    )

    logger.info("=== Scheduled sync complete ===")


async def run_scheduled_actions() -> None:
    """Execute any scheduled actions that are due."""
    from chief_of_staff.knowledge.database import get_due_actions, mark_action_run
    from chief_of_staff.agent.activity import log_activity, SCHEDULED_ACTION_RUN, ERROR

    now = datetime.utcnow().isoformat()
    try:
        actions = get_due_actions(now)
    except Exception as e:
        logger.error(f"Failed to query scheduled actions: {e}")
        return

    for action in actions:
        try:
            await _execute_scheduled_action(action)
            mark_action_run(action["id"], now)
            log_activity(
                agent_name="chief_of_staff",
                action_type=SCHEDULED_ACTION_RUN,
                action_detail=f"{action['action_type']}: {action.get('prompt', '')[:100]}",
                channel="scheduler",
                metadata={"action_id": action["id"], "action_type": action["action_type"]},
            )
        except Exception as e:
            logger.error(f"Scheduled action {action['id']} ({action['action_type']}) failed: {e}", exc_info=True)
            log_activity(
                agent_name="chief_of_staff",
                action_type=ERROR,
                action_detail=f"Scheduled action failed: {action['action_type']}: {e}",
                channel="scheduler",
            )


async def _execute_scheduled_action(action: dict) -> None:
    """Dispatch a scheduled action by its type."""
    action_type = action["action_type"]
    channel = action.get("channel", "discord")
    target = action.get("target", "")

    if action_type == "daily_briefing":
        from chief_of_staff.agent.briefing import generate_daily_briefing
        result = await generate_daily_briefing()
        if result and target:
            from chief_of_staff.communication.discord_bot import send_to_channel
            await send_to_channel(target, result)

    elif action_type == "weekly_pulse":
        from chief_of_staff.agent.team_health import generate_weekly_pulse
        result = await generate_weekly_pulse()
        if result and target:
            from chief_of_staff.communication.discord_bot import send_to_channel
            await send_to_channel(target, result)

    elif action_type == "engagement_check":
        from chief_of_staff.agent.team_health import check_engagement_alerts
        alerts = await check_engagement_alerts()
        if alerts and target:
            from chief_of_staff.communication.discord_bot import send_to_channel
            await send_to_channel(target, "\n\n".join(alerts))

    elif action_type == "research":
        from chief_of_staff.agent.core import Agent
        from chief_of_staff.agent.registry import get_registry
        config = get_registry().get("chief_of_staff")
        if config:
            agent = Agent(config)
            result = await agent.respond(
                user_message=action["prompt"],
                channel="scheduler",
                user_id="scheduled_research",
            )
            if result and target:
                from chief_of_staff.communication.discord_bot import send_to_channel
                await send_to_channel(target, result)

    elif action_type == "custom":
        from chief_of_staff.agent.core import Agent
        from chief_of_staff.agent.registry import get_registry
        config = get_registry().get("chief_of_staff")
        if config:
            agent = Agent(config)
            result = await agent.respond(
                user_message=action["prompt"],
                channel="scheduler",
                user_id="scheduled_custom",
            )
            if result and target and channel in ("discord", "both"):
                from chief_of_staff.communication.discord_bot import send_to_channel
                await send_to_channel(target, result)

    else:
        logger.warning(f"Unknown scheduled action type: {action_type}")


async def _debrief_new_calls(count: int) -> None:
    """Generate debriefs for recently ingested ElevenLabs call transcripts."""
    try:
        from chief_of_staff.knowledge import store as knowledge_store
        from chief_of_staff.agent.briefing import generate_meeting_debrief, post_meeting_debrief

        # Search for recently ingested call transcripts
        results = knowledge_store.search(
            query="call transcript",
            n_results=min(count, 5),
            source_filter="elevenlabs",
        )

        for r in results:
            title = r["metadata"].get("title", "ElevenLabs Call")
            transcript = r["text"]
            if transcript:
                feedback, is_important = await generate_meeting_debrief(title, transcript)
                if feedback:
                    await post_meeting_debrief(title, feedback, is_important)
    except Exception as e:
        logger.error(f"ElevenLabs call debrief failed: {e}", exc_info=True)


def start_scheduler():
    """Start the background sync loop."""
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_sync_loop())
        logger.info(f"Background scheduler started (interval: {SYNC_INTERVAL_SECONDS}s)")
