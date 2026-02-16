"""Recall.ai webhook handlers — real-time transcript delivery and bot status updates.

Handles:
- Real-time transcript chunks (streamed during the meeting)
- Bot status changes (joined, recording, done)
- Final transcript delivery (after meeting ends)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Request

from chief_of_staff.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/recall", tags=["recall"])


@router.post("/transcript")
async def recall_real_time_transcript(request: Request) -> dict:
    """Receive real-time transcript chunks from Recall.ai during a meeting.

    These arrive as the meeting happens, allowing near-real-time
    knowledge ingestion. We buffer them and do a final ingest when
    the meeting ends.
    """
    payload = await request.json()
    bot_id = payload.get("bot_id", "unknown")
    transcript = payload.get("transcript", {})

    speaker = transcript.get("speaker", "Unknown")
    text = " ".join(w.get("text", "") for w in transcript.get("words", []))

    if text.strip():
        logger.debug(f"[Recall RT] Bot {bot_id[:8]} | {speaker}: {text[:100]}...")

    return {"status": "ok"}


@router.post("/status")
async def recall_bot_status(request: Request) -> dict:
    """Handle bot status change webhooks from Recall.ai.

    Status flow: ready → joining → in_call → recording → done
    When status is 'done', we trigger full transcript ingestion.
    """
    payload = await request.json()

    event = payload.get("event", "")
    bot_id = payload.get("data", {}).get("bot_id", "unknown")
    status = payload.get("data", {}).get("status", {}).get("code", "unknown")

    logger.info(f"Recall bot status: {bot_id[:8]} → {status} (event: {event})")

    # Track webhook
    from chief_of_staff.agent.activity import log_activity, WEBHOOK_RECEIVED, MEETING_INGESTED
    log_activity(
        agent_name="chief_of_staff",
        action_type=WEBHOOK_RECEIVED,
        action_detail=f"Recall.ai bot {bot_id[:8]}: {status}",
        channel="recall",
        metadata={"bot_id": bot_id, "status": status, "event": event},
    )

    if status == "done":
        # Meeting is over — ingest the full transcript
        logger.info(f"Recall bot {bot_id[:8]} done — ingesting full transcript")
        try:
            from chief_of_staff.ingestion.recall_bot import ingest_bot_transcript

            meeting_url = payload.get("data", {}).get("meeting_url", "")
            doc_id = await ingest_bot_transcript(
                bot_id=bot_id,
                meeting_url=meeting_url,
            )
            logger.info(f"Recall transcript ingested: {doc_id}")

            log_activity(
                agent_name="chief_of_staff",
                action_type=MEETING_INGESTED,
                action_detail=f"Recall.ai transcript ingested: {doc_id}",
                channel="recall",
                metadata={"bot_id": bot_id, "doc_id": doc_id},
            )

            # Notify founders
            await _notify_founders_transcript_ready(bot_id, doc_id)

            # Generate AI debrief in background
            asyncio.create_task(_trigger_meeting_debrief(bot_id, doc_id))

        except Exception as e:
            logger.error(f"Failed to ingest Recall transcript for bot {bot_id}: {e}")

    elif status == "fatal":
        logger.error(f"Recall bot {bot_id[:8]} hit a fatal error: {payload}")

    return {"status": "ok"}


async def _notify_founders_transcript_ready(bot_id: str, doc_id: str) -> None:
    """Notify founders that a meeting transcript is ready."""
    try:
        from chief_of_staff.ingestion.recall_bot import get_bot_status
        from chief_of_staff.communication.sms import send_sms

        bot_info = await get_bot_status(bot_id)
        title = bot_info.get("metadata", {}).get("title", "a meeting")

        for phone in settings.founder_phone_numbers:
            await send_sms(
                to=phone,
                body=f"[Chief of Staff] Transcript ready for '{title}'. Ask me anything about it.",
            )
    except Exception as e:
        logger.error(f"Failed to send transcript notification: {e}")


async def _trigger_meeting_debrief(bot_id: str, doc_id: str) -> None:
    """Generate and post a meeting debrief in the background."""
    try:
        from chief_of_staff.ingestion.recall_bot import get_bot_status
        from chief_of_staff.knowledge import store as knowledge_store

        # Get meeting title
        bot_info = await get_bot_status(bot_id)
        title = bot_info.get("metadata", {}).get("title", "a meeting")

        # Retrieve the transcript from the knowledge base
        results = knowledge_store.search(query=doc_id, n_results=1)
        transcript_text = results[0]["text"] if results else ""

        if not transcript_text:
            logger.warning(f"No transcript found for debrief: bot={bot_id}, doc={doc_id}")
            return

        from chief_of_staff.agent.briefing import generate_meeting_debrief, post_meeting_debrief
        feedback, is_important = await generate_meeting_debrief(title, transcript_text)
        if feedback:
            await post_meeting_debrief(title, feedback, is_important)
    except Exception as e:
        logger.error(f"Meeting debrief failed for bot {bot_id}: {e}", exc_info=True)
