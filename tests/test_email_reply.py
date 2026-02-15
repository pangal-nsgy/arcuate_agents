"""Tests for email threading, CC logic, and conversation history."""

from __future__ import annotations

import base64
from email import message_from_bytes
from unittest.mock import MagicMock, patch

import pytest

from chief_of_staff.communication.email import send_email
from chief_of_staff.webhooks.gmail import _extract_email


# --- Threading header tests ---

@pytest.mark.asyncio
async def test_send_email_sets_in_reply_to_header():
    """In-Reply-To header is set when in_reply_to param is provided."""
    mock_service = MagicMock()
    mock_service.users().messages().send().execute.return_value = {"id": "sent_123"}

    with patch("chief_of_staff.communication.email.get_gmail_service", return_value=mock_service):
        await send_email(
            to="test@example.com",
            subject="Re: Hello",
            body="Reply body",
            in_reply_to="<orig-msg-id@example.com>",
        )

    # Extract the raw MIME message that was sent
    call_args = mock_service.users().messages().send.call_args
    raw_b64 = call_args[1]["body"]["raw"] if "body" in call_args[1] else call_args[0][0]["raw"]
    raw_bytes = base64.urlsafe_b64decode(raw_b64)
    msg = message_from_bytes(raw_bytes)

    assert msg["In-Reply-To"] == "<orig-msg-id@example.com>"


@pytest.mark.asyncio
async def test_send_email_sets_references_header():
    """References header is set when references param is provided."""
    mock_service = MagicMock()
    mock_service.users().messages().send().execute.return_value = {"id": "sent_123"}

    with patch("chief_of_staff.communication.email.get_gmail_service", return_value=mock_service):
        await send_email(
            to="test@example.com",
            subject="Re: Hello",
            body="Reply body",
            references="<msg1@ex.com> <msg2@ex.com>",
        )

    call_args = mock_service.users().messages().send.call_args
    raw_b64 = call_args[1]["body"]["raw"] if "body" in call_args[1] else call_args[0][0]["raw"]
    raw_bytes = base64.urlsafe_b64decode(raw_b64)
    msg = message_from_bytes(raw_bytes)

    assert msg["References"] == "<msg1@ex.com> <msg2@ex.com>"


@pytest.mark.asyncio
async def test_send_email_passes_thread_id_to_gmail():
    """Gmail threadId is included in the send body when thread_id is provided."""
    mock_service = MagicMock()
    mock_service.users().messages().send().execute.return_value = {"id": "sent_123"}

    with patch("chief_of_staff.communication.email.get_gmail_service", return_value=mock_service):
        await send_email(
            to="test@example.com",
            subject="Re: Hello",
            body="Reply body",
            thread_id="thread_abc",
        )

    call_args = mock_service.users().messages().send.call_args
    send_body = call_args[1]["body"] if "body" in call_args[1] else call_args[0][0]
    assert send_body["threadId"] == "thread_abc"


@pytest.mark.asyncio
async def test_send_email_no_thread_id_when_not_provided():
    """Gmail threadId is NOT included when thread_id is empty."""
    mock_service = MagicMock()
    mock_service.users().messages().send().execute.return_value = {"id": "sent_123"}

    with patch("chief_of_staff.communication.email.get_gmail_service", return_value=mock_service):
        await send_email(
            to="test@example.com",
            subject="Hello",
            body="Body",
        )

    call_args = mock_service.users().messages().send.call_args
    send_body = call_args[1]["body"] if "body" in call_args[1] else call_args[0][0]
    assert "threadId" not in send_body


# --- CC/BCC tests ---

@pytest.mark.asyncio
async def test_send_email_sets_cc_header():
    """CC header is set when cc param is provided."""
    mock_service = MagicMock()
    mock_service.users().messages().send().execute.return_value = {"id": "sent_123"}

    with patch("chief_of_staff.communication.email.get_gmail_service", return_value=mock_service):
        await send_email(
            to="test@example.com",
            subject="Hello",
            body="Body",
            cc="founder1@example.com, founder2@example.com",
        )

    call_args = mock_service.users().messages().send.call_args
    raw_b64 = call_args[1]["body"]["raw"] if "body" in call_args[1] else call_args[0][0]["raw"]
    raw_bytes = base64.urlsafe_b64decode(raw_b64)
    msg = message_from_bytes(raw_bytes)

    assert "founder1@example.com" in msg["cc"]
    assert "founder2@example.com" in msg["cc"]


@pytest.mark.asyncio
async def test_send_email_sets_bcc_header():
    """BCC header is set when bcc param is provided."""
    mock_service = MagicMock()
    mock_service.users().messages().send().execute.return_value = {"id": "sent_123"}

    with patch("chief_of_staff.communication.email.get_gmail_service", return_value=mock_service):
        await send_email(
            to="test@example.com",
            subject="Hello",
            body="Body",
            bcc="hidden@example.com",
        )

    call_args = mock_service.users().messages().send.call_args
    raw_b64 = call_args[1]["body"]["raw"] if "body" in call_args[1] else call_args[0][0]["raw"]
    raw_bytes = base64.urlsafe_b64decode(raw_b64)
    msg = message_from_bytes(raw_bytes)

    assert msg["bcc"] == "hidden@example.com"


@pytest.mark.asyncio
async def test_send_email_no_cc_bcc_when_empty():
    """CC/BCC headers are omitted when params are empty strings."""
    mock_service = MagicMock()
    mock_service.users().messages().send().execute.return_value = {"id": "sent_123"}

    with patch("chief_of_staff.communication.email.get_gmail_service", return_value=mock_service):
        await send_email(to="test@example.com", subject="Hello", body="Body")

    call_args = mock_service.users().messages().send.call_args
    raw_b64 = call_args[1]["body"]["raw"] if "body" in call_args[1] else call_args[0][0]["raw"]
    raw_bytes = base64.urlsafe_b64decode(raw_b64)
    msg = message_from_bytes(raw_bytes)

    assert msg["cc"] is None
    assert msg["bcc"] is None


# --- Conversation history tests ---

def test_email_conversation_round_trip(tmp_path):
    """Email conversations can be logged and retrieved by thread."""
    import sqlite3
    from unittest.mock import patch as _patch

    db_path = str(tmp_path / "test.db")
    with _patch("chief_of_staff.knowledge.database.settings") as mock_settings:
        mock_settings.sqlite_db_path = db_path

        from chief_of_staff.knowledge.database import init_db, log_email_conversation, get_email_thread
        init_db()

        # Log inbound
        log_email_conversation(
            conv_id="conv1",
            email_address="user@example.com",
            direction="inbound",
            body="Hey, I have a question",
            thread_id="thread_1",
            gmail_message_id="gm_1",
            subject="Question",
        )

        # Log outbound reply
        log_email_conversation(
            conv_id="conv2",
            email_address="user@example.com",
            direction="outbound",
            body="Sure, how can I help?",
            thread_id="thread_1",
            gmail_message_id="gm_2",
            subject="Re: Question",
        )

        thread = get_email_thread("thread_1")
        assert len(thread) == 2
        assert thread[0]["direction"] == "inbound"
        assert thread[1]["direction"] == "outbound"
        assert thread[0]["body"] == "Hey, I have a question"
        assert thread[1]["body"] == "Sure, how can I help?"


def test_email_conversation_deduplication(tmp_path):
    """Duplicate gmail_message_id is silently ignored."""
    from unittest.mock import patch as _patch

    db_path = str(tmp_path / "test.db")
    with _patch("chief_of_staff.knowledge.database.settings") as mock_settings:
        mock_settings.sqlite_db_path = db_path

        from chief_of_staff.knowledge.database import init_db, log_email_conversation, get_email_thread
        init_db()

        log_email_conversation(
            conv_id="conv1", email_address="a@b.com", direction="inbound",
            body="First", thread_id="t1", gmail_message_id="gm_dup",
        )
        # Same gmail_message_id — should be silently ignored
        log_email_conversation(
            conv_id="conv2", email_address="a@b.com", direction="inbound",
            body="Duplicate", thread_id="t1", gmail_message_id="gm_dup",
        )

        thread = get_email_thread("t1")
        assert len(thread) == 1
        assert thread[0]["body"] == "First"


# --- References chain tests ---

def test_references_chain_builds_from_thread_history(tmp_path):
    """References header includes all prior Message-IDs from the thread."""
    from unittest.mock import patch as _patch

    db_path = str(tmp_path / "test.db")
    with _patch("chief_of_staff.knowledge.database.settings") as mock_settings:
        mock_settings.sqlite_db_path = db_path

        from chief_of_staff.knowledge.database import init_db, log_email_conversation, get_email_thread
        init_db()

        # Simulate a 3-message thread with RFC Message-IDs
        log_email_conversation(
            conv_id="c1", email_address="user@ex.com", direction="inbound",
            body="First", thread_id="t1", gmail_message_id="gm1",
            rfc_message_id="<msg1@ex.com>", subject="Hello",
        )
        log_email_conversation(
            conv_id="c2", email_address="user@ex.com", direction="outbound",
            body="Reply 1", thread_id="t1", gmail_message_id="gm2",
            rfc_message_id="<msg2@ex.com>", subject="Re: Hello",
        )
        log_email_conversation(
            conv_id="c3", email_address="user@ex.com", direction="inbound",
            body="Follow-up", thread_id="t1", gmail_message_id="gm3",
            rfc_message_id="<msg3@ex.com>", subject="Re: Hello",
        )

        thread = get_email_thread("t1")

        # Reproduce the References assembly logic from _send_reply
        current_message_id = "<msg4@ex.com>"
        prior_refs = [
            t["rfc_message_id"] for t in thread if t.get("rfc_message_id")
        ]
        if current_message_id not in prior_refs:
            prior_refs.append(current_message_id)
        references = " ".join(prior_refs)

        assert references == "<msg1@ex.com> <msg2@ex.com> <msg3@ex.com> <msg4@ex.com>"


def test_references_deduplicates_current_message_id(tmp_path):
    """If the current Message-ID is already in the thread, don't duplicate it."""
    from unittest.mock import patch as _patch

    db_path = str(tmp_path / "test.db")
    with _patch("chief_of_staff.knowledge.database.settings") as mock_settings:
        mock_settings.sqlite_db_path = db_path

        from chief_of_staff.knowledge.database import init_db, log_email_conversation, get_email_thread
        init_db()

        log_email_conversation(
            conv_id="c1", email_address="user@ex.com", direction="inbound",
            body="Msg", thread_id="t1", gmail_message_id="gm1",
            rfc_message_id="<msg1@ex.com>", subject="Test",
        )

        thread = get_email_thread("t1")
        current_message_id = "<msg1@ex.com>"  # Same as existing
        prior_refs = [t["rfc_message_id"] for t in thread if t.get("rfc_message_id")]
        if current_message_id not in prior_refs:
            prior_refs.append(current_message_id)

        assert prior_refs == ["<msg1@ex.com>"]  # No duplicate


# --- Helper tests ---

def test_extract_email_from_header():
    """_extract_email parses Name <email> format."""
    assert _extract_email("Dan <dan@example.com>") == "dan@example.com"
    assert _extract_email("dan@example.com") == "dan@example.com"
    assert _extract_email("  dan@example.com  ") == "dan@example.com"
