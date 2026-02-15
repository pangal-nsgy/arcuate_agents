"""Gmail API — send emails on behalf of the Chief of Staff."""

from __future__ import annotations

import base64
import logging
from email.mime.text import MIMEText

from chief_of_staff.communication._google_auth import get_gmail_service

logger = logging.getLogger(__name__)


async def send_email(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
    in_reply_to: str = "",
    references: str = "",
    thread_id: str = "",
) -> str:
    """Send an email via the Gmail API.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Plain-text email body.
        cc: Comma-separated CC addresses.
        bcc: Comma-separated BCC addresses.
        in_reply_to: RFC 2822 Message-ID of the email being replied to.
        references: Space-separated list of Message-IDs for the thread.
        thread_id: Gmail thread ID — ensures reply groups in the same thread.

    Returns the Gmail message ID on success.
    """
    service = get_gmail_service()

    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject

    if cc:
        message["cc"] = cc
    if bcc:
        message["bcc"] = bcc
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
    if references:
        message["References"] = references

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    send_body: dict = {"raw": raw}
    if thread_id:
        send_body["threadId"] = thread_id

    result = service.users().messages().send(
        userId="me",
        body=send_body,
    ).execute()

    msg_id = result.get("id", "unknown")
    logger.info(f"Email sent to {to}, subject='{subject}', id={msg_id}")
    return msg_id
