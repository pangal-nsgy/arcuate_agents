"""Gmail push notification webhook — fast ACK + async email processing with reply logic."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import uuid

from fastapi import APIRouter, Request

from chief_of_staff.config import settings
from chief_of_staff.ingestion.gmail import fetch_and_ingest_emails

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/gmail", tags=["gmail"])

# Patterns that indicate automated/no-reply senders
_NOREPLY_PATTERNS = re.compile(
    r"(noreply|no-reply|mailer-daemon|notifications@|bounce|postmaster@)",
    re.IGNORECASE,
)

# Keywords for complaint detection — grouped by severity
_COMPLAINT_KEYWORDS_CRITICAL = [
    "lawsuit", "attorney", "lawyer", "legal action", "bbb", "better business bureau",
]
_COMPLAINT_KEYWORDS_HIGH = [
    "furious", "angry", "terrible", "worst", "disgusted", "outraged", "unacceptable",
]
_COMPLAINT_KEYWORDS_MEDIUM = [
    "unhappy", "disappointed", "complaint", "complain", "unsubscribe",
    "stop calling", "remove me", "do not contact", "opt out", "stop emailing",
]


@router.post("/push")
async def gmail_push_notification(request: Request) -> dict:
    """Handle Gmail push notifications via Google Cloud Pub/Sub.

    Returns 200 immediately (fast ACK), then processes emails in background.
    This prevents Pub/Sub redelivery caused by slow agent.respond() calls.
    """
    body = await request.json()

    # Decode the Pub/Sub message
    message = body.get("message", {})
    if message.get("data"):
        data = json.loads(base64.b64decode(message["data"]).decode())
        email_address = data.get("emailAddress", "unknown")
        history_id = data.get("historyId", "unknown")
        logger.info(f"Gmail push: new mail for {email_address}, historyId={history_id}")

    # Verify subscription matches expected (basic authenticity check)
    # Pub/Sub push puts subscription at top level, not inside message
    subscription = body.get("subscription", "") or message.get("subscription", "")
    if settings.gmail_pubsub_subscription and subscription:
        if subscription != settings.gmail_pubsub_subscription:
            logger.warning(f"Gmail push: unexpected subscription '{subscription}', ignoring")
            return {"status": "ignored", "reason": "unknown_subscription"}

    # Track webhook receipt
    from chief_of_staff.agent.activity import log_activity, WEBHOOK_RECEIVED
    log_activity(
        agent_name="chief_of_staff",
        action_type=WEBHOOK_RECEIVED,
        action_detail="Gmail push notification",
        channel="gmail",
    )

    # Fire-and-forget background processing
    asyncio.create_task(_process_new_emails())

    return {"status": "ok"}


async def _process_new_emails() -> None:
    """Background task: fetch new emails, filter, ingest, and reply if appropriate."""
    from chief_of_staff.communication._google_auth import get_gmail_service
    from chief_of_staff.knowledge.database import (
        is_gmail_message_processed,
        mark_gmail_message_processed,
        log_email_conversation,
        log_complaint,
    )
    from chief_of_staff.agent.activity import (
        log_activity, EMAIL_RECEIVED, EMAIL_SKIPPED,
    )

    try:
        service = get_gmail_service()

        # Fetch recent emails with pagination (not is:unread — time-based to avoid races)
        all_messages: list[dict] = []
        page_token = None
        while len(all_messages) < 50:
            batch_size = min(50, 50 - len(all_messages))
            results = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda pt=page_token, bs=batch_size: service.users().messages().list(
                    userId="me", maxResults=bs, q="newer_than:1h", pageToken=pt,
                ).execute(),
            )
            batch = results.get("messages", [])
            if not batch:
                break
            all_messages.extend(batch)
            page_token = results.get("nextPageToken")
            if not page_token:
                break

        if not all_messages:
            return

        logger.info(f"Gmail push: processing {len(all_messages)} recent messages")

        for msg_ref in all_messages:
            gmail_id = msg_ref["id"]

            # Atomic claim: mark as processed FIRST to prevent concurrent duplicates.
            # If another task already claimed it, skip. Uses INSERT OR IGNORE.
            if is_gmail_message_processed(gmail_id):
                continue
            mark_gmail_message_processed(gmail_id)

            try:
                msg = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda gid=gmail_id: service.users().messages().get(
                        userId="me", id=gid, format="full",
                    ).execute(),
                )

                headers = {h["name"].lower(): h["value"] for h in msg["payload"]["headers"]}
                from_addr = headers.get("from", "unknown")
                to_addr = headers.get("to", "")
                cc_addr = headers.get("cc", "")
                subject = headers.get("subject", "(no subject)")
                message_id = headers.get("message-id", "")
                in_reply_to = headers.get("in-reply-to", "")
                thread_id = msg.get("threadId", "")
                labels = msg.get("labelIds", [])

                # Only reply to emails addressed to the agent (To or CC)
                if not _is_addressed_to_agent(to_addr, cc_addr):
                    log_activity(
                        agent_name="chief_of_staff",
                        action_type=EMAIL_SKIPPED,
                        action_detail=f"Skipped: not addressed to agent",
                        channel="gmail",
                        user_id=from_addr,
                        metadata={"gmail_id": gmail_id, "to": to_addr, "cc": cc_addr},
                    )
                    continue

                # Extract plain-text body
                body = _extract_body(msg["payload"])

                # Run enterprise filters
                skip_reason = _is_filtered(from_addr, headers, labels)
                if skip_reason:
                    log_activity(
                        agent_name="chief_of_staff",
                        action_type=EMAIL_SKIPPED,
                        action_detail=f"Skipped: {skip_reason}",
                        channel="gmail",
                        user_id=from_addr,
                        metadata={"gmail_id": gmail_id, "reason": skip_reason},
                    )
                    continue

                # Log as received
                log_activity(
                    agent_name="chief_of_staff",
                    action_type=EMAIL_RECEIVED,
                    action_detail=f"From {from_addr}: {subject}",
                    channel="gmail",
                    user_id=from_addr,
                    metadata={"gmail_id": gmail_id, "thread_id": thread_id},
                )

                # Ingest into knowledge base (sync function — run in executor)
                ingest_query = f"rfc822msgid:{message_id}" if message_id else f"in:{gmail_id}"
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda q=ingest_query: fetch_and_ingest_emails(max_results=1, query=q),
                )

                # Detect complaints
                is_complaint, severity, complaint_summary = _detect_complaint(body, subject)
                if is_complaint:
                    log_complaint(
                        complaint_id=str(uuid.uuid4()),
                        source="email",
                        sender=from_addr,
                        summary=complaint_summary,
                        thread_id=thread_id,
                        severity=severity,
                    )
                    logger.info(f"Complaint detected from {from_addr}: [{severity}] {complaint_summary}")

                # Generate reply via agent (before logging inbound turn,
                # so conversation history doesn't include the current message twice)
                await _send_reply(
                    service=service,
                    from_addr=from_addr,
                    subject=subject,
                    body=body,
                    thread_id=thread_id,
                    message_id=message_id,
                    gmail_id=gmail_id,
                    complaint_severity=severity if is_complaint else "",
                )

                # Log inbound conversation turn (after reply, to avoid race with history)
                log_email_conversation(
                    conv_id=str(uuid.uuid4()),
                    email_address=from_addr,
                    direction="inbound",
                    body=body,
                    thread_id=thread_id,
                    gmail_message_id=gmail_id,
                    rfc_message_id=message_id,
                    subject=subject,
                )

            except Exception as e:
                # Don't mark-unprocessed on failure — already claimed above.
                # Pub/Sub may redeliver, but the claim prevents duplicate replies.
                # Log with full context for debugging.
                logger.error(f"Failed to process email {gmail_id}: {e}", exc_info=True)

    except Exception as e:
        logger.error(f"Gmail push background task failed: {e}", exc_info=True)


async def _send_reply(
    service,
    from_addr: str,
    subject: str,
    body: str,
    thread_id: str,
    message_id: str,
    gmail_id: str,
    complaint_severity: str = "",
) -> None:
    """Build conversation context, call agent.respond(), and send a threaded reply."""
    from chief_of_staff.agent.core import Agent
    from chief_of_staff.agent.registry import get_registry
    from chief_of_staff.communication.email import send_email
    from chief_of_staff.knowledge.database import get_email_thread, log_email_conversation
    from chief_of_staff.agent.activity import log_activity, EMAIL_SENT

    # Build conversation history from prior emails in this thread
    thread_history = get_email_thread(thread_id, limit=20) if thread_id else []
    conversation = []
    for turn in thread_history:
        role = "user" if turn["direction"] == "inbound" else "assistant"
        conversation.append({"role": role, "content": turn["body"]})

    # Current email (not yet logged to DB, so always append)
    conversation.append({"role": "user", "content": body})

    # Get agent response
    registry = get_registry()
    config = registry.get("chief_of_staff")
    if not config:
        logger.error("Cannot reply to email — chief_of_staff agent config not found")
        return

    agent = Agent(config)
    reply_text = await agent.respond(
        user_message=body,
        conversation_history=conversation[:-1] if len(conversation) > 1 else None,
        channel="gmail",
        user_id=from_addr,
    )

    if not reply_text or not reply_text.strip():
        logger.warning(f"Agent returned empty reply for email from {from_addr}")
        return

    # Determine CC/BCC for founder visibility
    # Complaints always BCC founders for passive awareness
    cc = ""
    bcc = ""
    sender_email = _extract_email(from_addr)
    founder_emails = [e for e in settings.founder_emails if e.lower() != sender_email.lower()]

    if founder_emails:
        founders_str = ", ".join(founder_emails)
        if complaint_severity or settings.email_visibility_mode == "bcc":
            bcc = founders_str
        else:
            cc = founders_str

    # Build threading headers
    reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"

    # Build References from prior thread Message-IDs + current message
    prior_refs = [
        t["rfc_message_id"] for t in thread_history
        if t.get("rfc_message_id")
    ]
    if message_id and message_id not in prior_refs:
        prior_refs.append(message_id)
    references = " ".join(prior_refs)

    # Send threaded reply
    sent_id = await send_email(
        to=from_addr,
        subject=reply_subject,
        body=reply_text,
        cc=cc,
        bcc=bcc,
        in_reply_to=message_id,
        references=references,
        thread_id=thread_id,
    )

    # Log outbound conversation turn
    log_email_conversation(
        conv_id=str(uuid.uuid4()),
        email_address=from_addr,
        direction="outbound",
        body=reply_text,
        thread_id=thread_id,
        gmail_message_id=sent_id,
        subject=reply_subject,
    )

    log_activity(
        agent_name="chief_of_staff",
        action_type=EMAIL_SENT,
        action_detail=f"Reply to {from_addr}: {reply_subject}",
        channel="gmail",
        user_id=from_addr,
        metadata={
            "gmail_id": sent_id,
            "thread_id": thread_id,
            "cc": cc,
            "bcc": bcc,
        },
    )

    logger.info(f"Email reply sent to {from_addr}, thread={thread_id}, id={sent_id}")


def _is_addressed_to_agent(to_addr: str, cc_addr: str) -> bool:
    """Check if the agent's email appears in the To or CC fields."""
    agent_email = settings.chief_email.lower()
    if not agent_email:
        return True  # No agent email configured — process all
    combined = f"{to_addr} {cc_addr}".lower()
    return agent_email in combined


def _is_filtered(from_addr: str, headers: dict[str, str], labels: list[str]) -> str | None:
    """Check if an email should be filtered (not replied to).

    Returns the skip reason, or None if the email should be processed.
    """
    # Self-sent: from address matches agent email (exact match on extracted address)
    agent_email = settings.chief_email.lower()
    if agent_email and _extract_email(from_addr).lower() == agent_email:
        return "self_sent"

    # Auto-Submitted header (RFC 3834): any value other than "no" = automated
    auto_submitted = headers.get("auto-submitted", "").lower()
    if auto_submitted and auto_submitted != "no":
        return f"auto_submitted:{auto_submitted}"

    # Precedence header: bulk, junk, list = mass mail
    precedence = headers.get("precedence", "").lower()
    if precedence in ("bulk", "junk", "list"):
        return f"precedence:{precedence}"

    # Noreply/automated sender patterns
    if _NOREPLY_PATTERNS.search(from_addr):
        return "noreply_sender"

    # List-Unsubscribe header = mailing list
    if headers.get("list-unsubscribe"):
        return "mailing_list"

    # Gmail category labels (promotions, updates, forums)
    filtered_labels = {"CATEGORY_PROMOTIONS", "CATEGORY_UPDATES", "CATEGORY_FORUMS"}
    matching = filtered_labels.intersection(set(labels))
    if matching:
        return f"gmail_category:{','.join(matching)}"

    return None


def _detect_complaint(body: str, subject: str) -> tuple[bool, str, str]:
    """Detect if an email contains a complaint using keyword heuristics.

    Returns (is_complaint, severity, summary).
    """
    text = f"{subject} {body}".lower()

    # Check critical keywords first
    for kw in _COMPLAINT_KEYWORDS_CRITICAL:
        if kw in text:
            return True, "critical", f"Legal/escalation keyword detected: '{kw}'"

    for kw in _COMPLAINT_KEYWORDS_HIGH:
        if kw in text:
            return True, "high", f"Strong negative sentiment: '{kw}'"

    for kw in _COMPLAINT_KEYWORDS_MEDIUM:
        if kw in text:
            return True, "medium", f"Complaint/opt-out keyword: '{kw}'"

    return False, "", ""


def _extract_email(from_header: str) -> str:
    """Extract bare email address from a From header like 'Name <email@example.com>'."""
    match = re.search(r"<([^>]+)>", from_header)
    if match:
        return match.group(1)
    # Might already be a bare email
    if "@" in from_header:
        return from_header.strip()
    return from_header


def _extract_body(payload: dict) -> str:
    """Extract plain text body from a Gmail message payload."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    parts = payload.get("parts", [])
    for part in parts:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")

    for part in parts:
        result = _extract_body(part)
        if result:
            return result

    return "(no text body)"
