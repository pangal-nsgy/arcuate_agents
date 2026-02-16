"""Zoom webhook handlers — real-time meeting events.

Handles Zoom webhook events:
- meeting.started: Log that a meeting began (optionally send bot)
- meeting.ended: Log meeting completion
- recording.completed: Auto-ingest transcript when cloud recording is ready
- recording.transcript_completed: Ingest when transcript specifically is done

Setup:
1. Go to marketplace.zoom.us > Your App > Feature > Event Subscriptions
2. Add event subscription with endpoint: https://your-server.com/webhooks/zoom
3. Subscribe to: meeting.started, meeting.ended, recording.completed,
   recording.transcript_completed
4. Copy the Secret Token for webhook verification
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from chief_of_staff.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/zoom", tags=["zoom"])


@router.post("")
async def zoom_webhook(
    request: Request,
    x_zm_request_timestamp: str = Header(""),
    x_zm_signature: str = Header(""),
):
    """Handle incoming Zoom webhook events.

    Zoom sends events for meeting lifecycle and recording completion.
    We use these to auto-ingest transcripts in real-time.
    """
    body = await request.body()
    payload = json.loads(body)

    # Handle Zoom's URL validation challenge (sent during webhook setup)
    event = payload.get("event", "")
    if event == "endpoint.url_validation":
        plain_token = payload["payload"]["plainToken"]
        hash_token = hmac.new(
            settings.zoom_webhook_secret.encode(),
            plain_token.encode(),
            hashlib.sha256,
        ).hexdigest()
        return {"plainToken": plain_token, "encryptedToken": hash_token}

    # Verify webhook signature
    if settings.zoom_webhook_secret and not _verify_signature(
        body, x_zm_request_timestamp, x_zm_signature
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    logger.info(f"Zoom webhook event: {event}")

    # Track webhook
    from chief_of_staff.agent.activity import log_activity, WEBHOOK_RECEIVED, MEETING_INGESTED
    log_activity(
        agent_name="chief_of_staff",
        action_type=WEBHOOK_RECEIVED,
        action_detail=f"Zoom: {event}",
        channel="zoom",
        metadata={"event": event},
    )

    # Route to appropriate handler
    if event == "meeting.started":
        await _handle_meeting_started(payload)
    elif event == "meeting.ended":
        await _handle_meeting_ended(payload)
    elif event in ("recording.completed", "recording.transcript_completed"):
        await _handle_recording_completed(payload)
    else:
        logger.info(f"Unhandled Zoom event: {event}")

    return {"status": "ok"}


def _verify_signature(body: bytes, timestamp: str, signature: str) -> bool:
    """Verify the Zoom webhook signature."""
    if not settings.zoom_webhook_secret:
        return True  # Skip verification if secret not configured

    message = f"v0:{timestamp}:{body.decode()}"
    expected = "v0=" + hmac.new(
        settings.zoom_webhook_secret.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


async def _handle_meeting_started(payload: dict[str, Any]) -> None:
    """Handle meeting.started event.

    Optionally dispatch a meeting bot (Recall.ai) to join and record.
    """
    meeting = payload.get("payload", {}).get("object", {})
    topic = meeting.get("topic", "Unknown")
    meeting_id = meeting.get("id", "")
    host_email = meeting.get("host", {}).get("email", "unknown")
    start_time = meeting.get("start_time", "")

    logger.info(f"Meeting started: '{topic}' (ID: {meeting_id}) hosted by {host_email}")

    # Check if this is an internal meeting we should auto-join with a bot
    if settings.zoom_auto_record_internal and _is_internal_meeting(host_email):
        logger.info(f"Internal meeting detected — dispatching recording bot for '{topic}'")
        try:
            from chief_of_staff.ingestion.recall_bot import dispatch_bot

            join_url = meeting.get("join_url", "")
            if join_url:
                await dispatch_bot(
                    meeting_url=join_url,
                    meeting_title=topic,
                )
        except ImportError:
            logger.debug("Recall.ai bot not configured — skipping auto-join")
        except Exception as e:
            logger.error(f"Failed to dispatch bot for meeting {meeting_id}: {e}")


async def _handle_meeting_ended(payload: dict[str, Any]) -> None:
    """Handle meeting.ended event — log meeting completion."""
    meeting = payload.get("payload", {}).get("object", {})
    topic = meeting.get("topic", "Unknown")
    meeting_id = meeting.get("id", "")
    duration = meeting.get("duration", 0)

    logger.info(f"Meeting ended: '{topic}' (ID: {meeting_id}, duration: {duration}min)")


async def _handle_recording_completed(payload: dict[str, Any]) -> None:
    """Handle recording.completed — auto-ingest the transcript.

    This is the key event: when Zoom finishes processing a cloud recording,
    we immediately pull the transcript and ingest it into the knowledge base.
    """
    meeting = payload.get("payload", {}).get("object", {})
    topic = meeting.get("topic", "Unknown")
    meeting_id = meeting.get("id", meeting.get("uuid", ""))
    host_email = meeting.get("host_email", "unknown")
    start_time = meeting.get("start_time", "")
    duration = meeting.get("duration", 0)

    logger.info(f"Recording completed for: '{topic}' (ID: {meeting_id})")

    recording_files = meeting.get("recording_files", [])
    transcript_ingested = False
    transcript_text = ""

    for rec_file in recording_files:
        file_type = rec_file.get("file_type", "")
        recording_type = rec_file.get("recording_type", "")
        download_url = rec_file.get("download_url", "")
        status = rec_file.get("status", "")

        if status != "completed" or not download_url:
            continue

        if recording_type in ("audio_transcript", "chat_file") or file_type == "TRANSCRIPT":
            try:
                from chief_of_staff.ingestion.zoom_client import get_recording_transcript
                from chief_of_staff.ingestion.zoom import parse_vtt_transcript
                from chief_of_staff.knowledge.store import ingest

                raw = await get_recording_transcript(download_url)

                if file_type == "TRANSCRIPT" or recording_type == "audio_transcript":
                    transcript_text = parse_vtt_transcript(raw)
                    content = (
                        f"Meeting: {topic}\n"
                        f"Date: {start_time}\n"
                        f"Duration: {duration} minutes\n"
                        f"Host: {host_email}\n"
                        f"Platform: Zoom\n"
                        f"\n--- Transcript ---\n{transcript_text}"
                    )
                    source_id = f"zoom_transcript_{meeting_id}"
                    title = f"Zoom Meeting: {topic}"
                else:
                    transcript_text = raw
                    content = (
                        f"Meeting Chat: {topic}\n"
                        f"Date: {start_time}\n"
                        f"Platform: Zoom\n"
                        f"\n--- Chat Log ---\n{raw}"
                    )
                    source_id = f"zoom_chat_{meeting_id}"
                    title = f"Zoom Chat: {topic}"

                ingest(
                    source="meeting",
                    source_id=source_id,
                    title=title,
                    content=content,
                    metadata={
                        "platform": "zoom",
                        "meeting_id": str(meeting_id),
                        "topic": topic,
                        "start_time": start_time,
                        "duration_minutes": duration,
                        "host_email": host_email,
                        "recording_type": recording_type,
                        "ingested_via": "webhook",
                    },
                )
                transcript_ingested = True
                logger.info(f"Auto-ingested Zoom transcript: {topic}")

                from chief_of_staff.agent.activity import log_activity, MEETING_INGESTED
                log_activity(
                    agent_name="chief_of_staff",
                    action_type=MEETING_INGESTED,
                    action_detail=f"Zoom transcript: {topic} ({duration}min)",
                    channel="zoom",
                    metadata={"meeting_id": str(meeting_id), "topic": topic, "host": host_email},
                )

            except Exception as e:
                logger.error(f"Failed to auto-ingest transcript for {meeting_id}: {e}")

    if transcript_ingested:
        # Notify founders that a meeting transcript is now available
        await _notify_transcript_ready(topic, start_time, duration)

        # Generate AI debrief in background
        if transcript_text:
            asyncio.create_task(_trigger_meeting_debrief(topic, transcript_text))


async def _notify_transcript_ready(topic: str, start_time: str, duration: int) -> None:
    """Send a notification to founders that a meeting transcript was ingested."""
    try:
        from chief_of_staff.communication.sms import send_sms

        for phone in settings.founder_phone_numbers:
            await send_sms(
                to=phone,
                body=(
                    f"[Chief of Staff] Meeting transcript ingested:\n"
                    f"'{topic}' ({duration}min, {start_time})\n"
                    f"Ask me anything about this meeting."
                ),
            )
    except Exception as e:
        logger.error(f"Failed to send transcript notification: {e}")


def _is_internal_meeting(host_email: str) -> bool:
    """Check if a meeting is hosted by an internal team member."""
    # Check against founder emails or company domain
    internal_domains = {"arcuate.health", "arcuatehealth.com"}
    domain = host_email.split("@")[-1].lower() if "@" in host_email else ""
    return domain in internal_domains


async def _trigger_meeting_debrief(topic: str, transcript_text: str) -> None:
    """Generate and post a meeting debrief in the background."""
    try:
        from chief_of_staff.agent.briefing import generate_meeting_debrief, post_meeting_debrief

        feedback, is_important = await generate_meeting_debrief(topic, transcript_text)
        if feedback:
            await post_meeting_debrief(topic, feedback, is_important)
    except Exception as e:
        logger.error(f"Meeting debrief failed for '{topic}': {e}", exc_info=True)
