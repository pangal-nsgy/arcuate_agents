"""Unit tests for BlueBubbles webhook payload normalization."""

from __future__ import annotations

from chief_of_staff.webhooks.bluebubbles import _extract_inbound


def test_extract_inbound_from_flat_payload():
    sender, chat_guid, text = _extract_inbound(
        {"handle": "+15551234567", "chatGuid": "iMessage;-;chat123", "text": "hello"}
    )
    assert sender == "+15551234567"
    assert chat_guid == "iMessage;-;chat123"
    assert text == "hello"


def test_extract_inbound_from_nested_data_payload():
    sender, chat_guid, text = _extract_inbound(
        {"data": {"sender": "foo@icloud.com", "guid": "iMessage;-;x", "message": "hey"}}
    )
    assert sender == "foo@icloud.com"
    assert chat_guid == "iMessage;-;x"
    assert text == "hey"


def test_extract_inbound_missing_fields_returns_empty_strings():
    sender, chat_guid, text = _extract_inbound({"data": {"unknown": "value"}})
    assert sender == ""
    assert chat_guid == ""
    assert text == ""

