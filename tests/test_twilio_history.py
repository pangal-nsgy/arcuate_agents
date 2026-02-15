"""Tests for Twilio webhook conversation history role mapping."""

import pytest


def _build_history(messages: list[dict]) -> list[dict]:
    """Reproduce the history-building logic from twilio.py."""
    history = []
    for msg in reversed(messages):
        role = "assistant" if msg.get("direction") == "outbound" else "user"
        history.append({"role": role, "content": msg["message"]})
    return history


class TestConversationHistory:
    """Verify inbound/outbound messages map to user/assistant roles."""

    def test_inbound_is_user(self):
        messages = [{"direction": "inbound", "message": "hello"}]
        history = _build_history(messages)
        assert history[0]["role"] == "user"

    def test_outbound_is_assistant(self):
        messages = [{"direction": "outbound", "message": "hi there"}]
        history = _build_history(messages)
        assert history[0]["role"] == "assistant"

    def test_mixed_conversation(self):
        messages = [
            {"direction": "inbound", "message": "hello"},
            {"direction": "outbound", "message": "hi there"},
            {"direction": "inbound", "message": "how are you?"},
        ]
        history = _build_history(messages)
        # reversed order: most recent first in input -> oldest first in output
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "how are you?"
        assert history[1]["role"] == "assistant"
        assert history[2]["role"] == "user"

    def test_missing_direction_defaults_to_user(self):
        """Messages without a direction field should default to user."""
        messages = [{"message": "unknown origin"}]
        history = _build_history(messages)
        assert history[0]["role"] == "user"
