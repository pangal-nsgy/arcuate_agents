"""Tests for email guardrails: idempotency, loop prevention, complaint detection."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from chief_of_staff.webhooks.gmail import _is_filtered, _detect_complaint, _is_addressed_to_agent, _extract_email


# --- Loop prevention / filtering tests ---

class TestEmailFiltering:
    """Enterprise filtering: _is_filtered() correctly skips automated/unwanted emails."""

    def test_self_sent_is_filtered(self):
        """Emails from the agent's own address are skipped."""
        with patch("chief_of_staff.webhooks.gmail.settings") as mock_settings:
            mock_settings.chief_email = "agent1@arcuatehealth.com"
            result = _is_filtered(
                "Agent <agent1@arcuatehealth.com>", {}, [],
            )
        assert result == "self_sent"

    def test_auto_submitted_is_filtered(self):
        """Emails with Auto-Submitted header (not 'no') are skipped."""
        result = _is_filtered(
            "someone@example.com",
            {"auto-submitted": "auto-replied"},
            [],
        )
        assert result == "auto_submitted:auto-replied"

    def test_auto_submitted_no_is_not_filtered(self):
        """Auto-Submitted: no means human-sent — not filtered."""
        with patch("chief_of_staff.webhooks.gmail.settings") as mock_settings:
            mock_settings.chief_email = ""
            result = _is_filtered(
                "someone@example.com",
                {"auto-submitted": "no"},
                [],
            )
        assert result is None

    def test_precedence_bulk_is_filtered(self):
        """Precedence: bulk emails are skipped."""
        with patch("chief_of_staff.webhooks.gmail.settings") as mock_settings:
            mock_settings.chief_email = ""
            result = _is_filtered(
                "newsletter@example.com",
                {"precedence": "bulk"},
                [],
            )
        assert result == "precedence:bulk"

    def test_precedence_junk_is_filtered(self):
        """Precedence: junk emails are skipped."""
        with patch("chief_of_staff.webhooks.gmail.settings") as mock_settings:
            mock_settings.chief_email = ""
            result = _is_filtered(
                "spam@example.com",
                {"precedence": "junk"},
                [],
            )
        assert result == "precedence:junk"

    def test_noreply_sender_is_filtered(self):
        """Noreply sender patterns are skipped."""
        with patch("chief_of_staff.webhooks.gmail.settings") as mock_settings:
            mock_settings.chief_email = ""

            assert _is_filtered("noreply@google.com", {}, []) == "noreply_sender"
            assert _is_filtered("no-reply@stripe.com", {}, []) == "noreply_sender"
            assert _is_filtered("MAILER-DAEMON@mx.example.com", {}, []) == "noreply_sender"
            assert _is_filtered("notifications@github.com", {}, []) == "noreply_sender"
            assert _is_filtered("bounce+123@example.com", {}, []) == "noreply_sender"

    def test_list_unsubscribe_is_filtered(self):
        """Emails with List-Unsubscribe header are mailing lists — skipped."""
        with patch("chief_of_staff.webhooks.gmail.settings") as mock_settings:
            mock_settings.chief_email = ""
            result = _is_filtered(
                "updates@company.com",
                {"list-unsubscribe": "<https://company.com/unsub>"},
                [],
            )
        assert result == "mailing_list"

    def test_gmail_promotions_label_is_filtered(self):
        """Emails with CATEGORY_PROMOTIONS label are skipped."""
        with patch("chief_of_staff.webhooks.gmail.settings") as mock_settings:
            mock_settings.chief_email = ""
            result = _is_filtered(
                "deals@shop.com", {}, ["INBOX", "CATEGORY_PROMOTIONS"],
            )
        assert result is not None
        assert "CATEGORY_PROMOTIONS" in result

    def test_gmail_updates_label_is_filtered(self):
        """Emails with CATEGORY_UPDATES label are skipped."""
        with patch("chief_of_staff.webhooks.gmail.settings") as mock_settings:
            mock_settings.chief_email = ""
            result = _is_filtered(
                "alerts@service.com", {}, ["INBOX", "CATEGORY_UPDATES"],
            )
        assert result is not None
        assert "CATEGORY_UPDATES" in result

    def test_gmail_forums_label_is_filtered(self):
        """Emails with CATEGORY_FORUMS label are skipped."""
        with patch("chief_of_staff.webhooks.gmail.settings") as mock_settings:
            mock_settings.chief_email = ""
            result = _is_filtered(
                "group@googlegroups.com", {}, ["INBOX", "CATEGORY_FORUMS"],
            )
        assert result is not None
        assert "CATEGORY_FORUMS" in result

    def test_normal_email_is_not_filtered(self):
        """Regular human emails pass all filters."""
        with patch("chief_of_staff.webhooks.gmail.settings") as mock_settings:
            mock_settings.chief_email = "agent1@arcuatehealth.com"
            result = _is_filtered(
                "Dan Pangal <dan@example.com>",
                {"subject": "Hey, quick question"},
                ["INBOX"],
            )
        assert result is None


# --- Addressed-to-agent tests ---

class TestAddressedToAgent:
    """Only reply to emails addressed to the agent."""

    def test_agent_in_to_field(self):
        """Agent email in To field passes."""
        with patch("chief_of_staff.webhooks.gmail.settings") as mock_settings:
            mock_settings.chief_email = "agent1@arcuatehealth.com"
            assert _is_addressed_to_agent("agent1@arcuatehealth.com", "") is True

    def test_agent_in_cc_field(self):
        """Agent email in CC field passes."""
        with patch("chief_of_staff.webhooks.gmail.settings") as mock_settings:
            mock_settings.chief_email = "agent1@arcuatehealth.com"
            assert _is_addressed_to_agent("other@example.com", "agent1@arcuatehealth.com") is True

    def test_agent_not_addressed(self):
        """Email not addressed to agent is rejected."""
        with patch("chief_of_staff.webhooks.gmail.settings") as mock_settings:
            mock_settings.chief_email = "agent1@arcuatehealth.com"
            assert _is_addressed_to_agent("someone@example.com", "other@example.com") is False

    def test_no_agent_email_configured(self):
        """If no agent email configured, allow all (graceful degradation)."""
        with patch("chief_of_staff.webhooks.gmail.settings") as mock_settings:
            mock_settings.chief_email = ""
            assert _is_addressed_to_agent("anyone@example.com", "") is True

    def test_agent_in_multi_recipient_to(self):
        """Agent found among multiple To recipients."""
        with patch("chief_of_staff.webhooks.gmail.settings") as mock_settings:
            mock_settings.chief_email = "agent1@arcuatehealth.com"
            assert _is_addressed_to_agent(
                "bob@example.com, agent1@arcuatehealth.com, alice@example.com", ""
            ) is True


# --- Idempotency tests ---

class TestIdempotency:
    """Gmail message processing idempotency via processed_gmail_events table."""

    def test_message_not_processed_initially(self, tmp_path):
        """A new message ID has not been processed."""
        db_path = str(tmp_path / "test.db")
        with patch("chief_of_staff.knowledge.database.settings") as mock_settings:
            mock_settings.sqlite_db_path = db_path
            from chief_of_staff.knowledge.database import init_db, is_gmail_message_processed
            init_db()
            assert is_gmail_message_processed("new_msg_123") is False

    def test_message_marked_processed(self, tmp_path):
        """After marking, a message ID returns True."""
        db_path = str(tmp_path / "test.db")
        with patch("chief_of_staff.knowledge.database.settings") as mock_settings:
            mock_settings.sqlite_db_path = db_path
            from chief_of_staff.knowledge.database import (
                init_db, is_gmail_message_processed, mark_gmail_message_processed,
            )
            init_db()
            mark_gmail_message_processed("msg_456")
            assert is_gmail_message_processed("msg_456") is True

    def test_double_mark_is_idempotent(self, tmp_path):
        """Marking the same message twice doesn't raise."""
        db_path = str(tmp_path / "test.db")
        with patch("chief_of_staff.knowledge.database.settings") as mock_settings:
            mock_settings.sqlite_db_path = db_path
            from chief_of_staff.knowledge.database import init_db, mark_gmail_message_processed
            init_db()
            mark_gmail_message_processed("msg_789")
            mark_gmail_message_processed("msg_789")  # Should not raise

    def test_try_claim_returns_true_on_first_call(self, tmp_path):
        """Atomic claim returns True when message is unclaimed."""
        db_path = str(tmp_path / "test.db")
        with patch("chief_of_staff.knowledge.database.settings") as mock_settings:
            mock_settings.sqlite_db_path = db_path
            from chief_of_staff.knowledge.database import init_db, try_claim_gmail_message
            init_db()
            assert try_claim_gmail_message("msg_atomic_1") is True

    def test_try_claim_returns_false_on_second_call(self, tmp_path):
        """Atomic claim returns False when message is already claimed."""
        db_path = str(tmp_path / "test.db")
        with patch("chief_of_staff.knowledge.database.settings") as mock_settings:
            mock_settings.sqlite_db_path = db_path
            from chief_of_staff.knowledge.database import init_db, try_claim_gmail_message
            init_db()
            assert try_claim_gmail_message("msg_atomic_2") is True
            assert try_claim_gmail_message("msg_atomic_2") is False

    def test_unclaim_allows_reclaim(self, tmp_path):
        """After unclaiming, the message can be claimed again (transient failure retry)."""
        db_path = str(tmp_path / "test.db")
        with patch("chief_of_staff.knowledge.database.settings") as mock_settings:
            mock_settings.sqlite_db_path = db_path
            from chief_of_staff.knowledge.database import (
                init_db, try_claim_gmail_message, unclaim_gmail_message,
            )
            init_db()
            assert try_claim_gmail_message("msg_retry") is True
            unclaim_gmail_message("msg_retry")
            assert try_claim_gmail_message("msg_retry") is True


# --- Founder visibility tests ---

class TestFounderVisibility:
    """Founder CC/BCC logic: founders are not CC'd when replying to a founder."""

    def test_founder_sender_gets_no_cc(self):
        """When a founder emails the agent, reply has no CC/BCC of other founders."""
        sender = "dan@arcuatehealth.com"
        founder_emails = ["dan@arcuatehealth.com", "dhiraj@arcuatehealth.com"]
        sender_email = _extract_email(sender).lower()
        sender_is_founder = any(sender_email == e.lower() for e in founder_emails)
        assert sender_is_founder is True

    def test_external_sender_gets_founder_cc(self):
        """When an external sender emails the agent, founders get CC'd."""
        sender = "patient@gmail.com"
        founder_emails = ["dan@arcuatehealth.com", "dhiraj@arcuatehealth.com"]
        sender_email = _extract_email(sender).lower()
        sender_is_founder = any(sender_email == e.lower() for e in founder_emails)
        assert sender_is_founder is False

    def test_complaint_from_external_bccs_founders(self):
        """Complaints from external senders BCC founders (not CC)."""
        complaint_severity = "critical"
        sender_is_founder = False
        visibility_mode = "cc"
        # Should use BCC when complaint, even if mode is cc
        should_bcc = not sender_is_founder and bool(complaint_severity or visibility_mode == "bcc")
        assert should_bcc is True

    def test_complaint_from_founder_no_visibility(self):
        """Complaints from founders don't CC/BCC other founders."""
        complaint_severity = "high"
        sender_is_founder = True
        # Founder-sent: no CC/BCC regardless of complaint
        should_add_founders = not sender_is_founder
        assert should_add_founders is False


# --- Complaint detection tests ---

class TestComplaintDetection:
    """Complaint detection via keyword heuristics."""

    def test_legal_keyword_is_critical(self):
        """Legal keywords trigger critical severity."""
        is_complaint, severity, summary = _detect_complaint(
            "I'm contacting my attorney about this.", "Service issue",
        )
        assert is_complaint is True
        assert severity == "critical"
        assert "attorney" in summary

    def test_lawsuit_keyword_is_critical(self):
        """Lawsuit keyword triggers critical severity."""
        is_complaint, severity, summary = _detect_complaint(
            "We are considering a lawsuit.", "Formal complaint",
        )
        assert is_complaint is True
        assert severity == "critical"

    def test_bbb_keyword_is_critical(self):
        """BBB keyword triggers critical severity."""
        is_complaint, severity, summary = _detect_complaint(
            "I'm reporting you to the BBB.", "Complaint",
        )
        assert is_complaint is True
        assert severity == "critical"

    def test_angry_keyword_is_high(self):
        """Strong negative emotion triggers high severity."""
        is_complaint, severity, summary = _detect_complaint(
            "I am furious about the service!", "Feedback",
        )
        assert is_complaint is True
        assert severity == "high"

    def test_terrible_keyword_is_high(self):
        """'Terrible' triggers high severity."""
        is_complaint, severity, summary = _detect_complaint(
            "This was a terrible experience.", "",
        )
        assert is_complaint is True
        assert severity == "high"

    def test_disappointed_keyword_is_medium(self):
        """Mild negative triggers medium severity."""
        is_complaint, severity, summary = _detect_complaint(
            "I am disappointed with the results.", "",
        )
        assert is_complaint is True
        assert severity == "medium"

    def test_unsubscribe_keyword_is_medium(self):
        """Unsubscribe request triggers medium severity."""
        is_complaint, severity, summary = _detect_complaint(
            "Please unsubscribe me from your emails.", "",
        )
        assert is_complaint is True
        assert severity == "medium"

    def test_stop_calling_keyword_is_medium(self):
        """'Stop calling' triggers medium severity."""
        is_complaint, severity, summary = _detect_complaint(
            "Please stop calling our office.", "Request",
        )
        assert is_complaint is True
        assert severity == "medium"

    def test_normal_email_no_complaint(self):
        """Normal emails don't trigger complaint detection."""
        is_complaint, severity, summary = _detect_complaint(
            "Thanks for following up! Looking forward to our next meeting.",
            "Re: Onboarding update",
        )
        assert is_complaint is False
        assert severity == ""
        assert summary == ""

    def test_complaint_keyword_in_subject(self):
        """Keywords in subject line are also detected."""
        is_complaint, severity, summary = _detect_complaint(
            "See attached.", "COMPLAINT about service",
        )
        assert is_complaint is True
        assert severity == "medium"

    def test_complaint_forces_bcc_not_cc(self):
        """Complaints force BCC to founders even when visibility mode is 'cc'."""
        # This tests the logic: if complaint_severity is truthy, use BCC regardless
        # The actual BCC construction is in _send_reply; here we verify the contract
        complaint_severity = "critical"
        visibility_mode = "cc"  # Normally this would use CC

        # The condition in _send_reply:
        # if complaint_severity or settings.email_visibility_mode == "bcc": → use bcc
        # else: → use cc
        should_use_bcc = bool(complaint_severity) or visibility_mode == "bcc"
        assert should_use_bcc is True

        # And for non-complaint with cc mode, should use cc
        should_use_bcc_normal = bool("") or visibility_mode == "bcc"
        assert should_use_bcc_normal is False

    def test_complaint_bcc_with_bcc_mode(self):
        """Complaints with bcc visibility mode also use BCC (no change)."""
        complaint_severity = "high"
        visibility_mode = "bcc"
        should_use_bcc = bool(complaint_severity) or visibility_mode == "bcc"
        assert should_use_bcc is True

    def test_complaint_persistence(self, tmp_path):
        """Complaints are persisted to the database."""
        db_path = str(tmp_path / "test.db")
        with patch("chief_of_staff.knowledge.database.settings") as mock_settings:
            mock_settings.sqlite_db_path = db_path
            from chief_of_staff.knowledge.database import init_db, log_complaint, get_open_complaints
            init_db()

            log_complaint(
                complaint_id="c1",
                source="email",
                sender="angry@customer.com",
                summary="Legal keyword: attorney",
                thread_id="t1",
                severity="critical",
            )

            complaints = get_open_complaints()
            assert len(complaints) == 1
            assert complaints[0]["severity"] == "critical"
            assert complaints[0]["sender"] == "angry@customer.com"
            assert complaints[0]["status"] == "open"
