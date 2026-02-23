"""Unit tests for BlueBubbles webhook payload normalization."""

from __future__ import annotations

from chief_of_staff.communication.bluebubbles_pairing import reset_bluebubbles_pairing_store_for_tests
from chief_of_staff.webhooks.bluebubbles import _evaluate_sender_policy, _extract_inbound


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


def test_dm_pairing_policy_requests_code_for_unknown_sender(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "chief_of_staff.communication.bluebubbles_pairing.settings.bluebubbles_pairing_store_path",
        str(tmp_path / "pairing.json"),
    )
    reset_bluebubbles_pairing_store_for_tests()
    monkeypatch.setattr("chief_of_staff.webhooks.bluebubbles.settings.bluebubbles_dm_policy", "pairing")
    monkeypatch.setattr("chief_of_staff.webhooks.bluebubbles.settings.bluebubbles_allow_from", [])

    allowed, reason, reply = _evaluate_sender_policy(
        sender="+15550001111",
        text="hello",
        payload={"data": {"chatGuid": "iMessage;-;x"}},
    )
    assert allowed is False
    assert reason == "dm_pairing_required"
    assert "Pairing required" in (reply or "")


def test_group_disabled_policy_ignores_message(monkeypatch):
    monkeypatch.setattr("chief_of_staff.webhooks.bluebubbles.settings.bluebubbles_group_policy", "disabled")

    allowed, reason, reply = _evaluate_sender_policy(
        sender="+15550001111",
        text="@chief hi",
        payload={"data": {"chatGuid": "chat123", "isGroup": True}},
    )
    assert allowed is False
    assert reason == "group_disabled"
    assert reply is None


def test_group_allowlist_requires_mention_when_enabled(monkeypatch):
    monkeypatch.setattr("chief_of_staff.webhooks.bluebubbles.settings.bluebubbles_group_policy", "allowlist")
    monkeypatch.setattr("chief_of_staff.webhooks.bluebubbles.settings.bluebubbles_group_allow_from", ["+15550001111"])
    monkeypatch.setattr(
        "chief_of_staff.webhooks.bluebubbles.settings.bluebubbles_require_mention_in_groups",
        True,
    )
    monkeypatch.setattr(
        "chief_of_staff.webhooks.bluebubbles.settings.bluebubbles_mention_keywords",
        ["@chief"],
    )

    allowed, reason, _ = _evaluate_sender_policy(
        sender="+15550001111",
        text="no mention here",
        payload={"data": {"chatGuid": "chat123", "isGroup": True}},
    )
    assert allowed is False
    assert reason == "group_no_mention"


def test_founder_sender_bypasses_pairing_policy(monkeypatch):
    monkeypatch.setattr("chief_of_staff.webhooks.bluebubbles.settings.bluebubbles_dm_policy", "pairing")
    monkeypatch.setattr(
        "chief_of_staff.webhooks.bluebubbles.settings.founder_phone_numbers",
        ["+15550001111"],
    )

    allowed, reason, reply = _evaluate_sender_policy(
        sender="+15550001111",
        text="hello",
        payload={"data": {"chatGuid": "iMessage;-;x"}},
    )
    assert allowed is True
    assert reason is None
    assert reply is None
