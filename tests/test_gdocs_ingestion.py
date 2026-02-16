"""Tests for Google Docs/Drive ingestion behavior."""

from __future__ import annotations

from types import SimpleNamespace

from chief_of_staff.ingestion.gdocs import _list_docs_from_drive, _list_accessible_shared_drive_ids


def test_list_docs_includes_all_drives_and_shared_drive_ids(monkeypatch):
    """Drive queries should include all-drives flags and configured shared drive IDs."""
    from chief_of_staff.config import settings

    monkeypatch.setattr(settings, "google_shared_drive_ids", "driveA, driveB")

    calls: list[dict] = []
    responses = [
        {"files": [{"id": "doc-1", "name": "A"}]},  # allDrives base query
        {"files": [{"id": "doc-2", "name": "B"}]},  # allDrives sharedWithMe query
        {"files": [{"id": "doc-3", "name": "C"}]},  # driveA
        {"files": [{"id": "doc-4", "name": "D"}]},  # driveB
    ]

    class _Files:
        def list(self, **kwargs):
            calls.append(kwargs)
            resp = responses.pop(0)
            return SimpleNamespace(execute=lambda: resp)

    drive = SimpleNamespace(files=lambda: _Files())
    files = _list_docs_from_drive(drive=drive, folder_id=None, max_results=10)

    assert len(files) == 4
    assert calls[0]["corpora"] == "allDrives"
    assert calls[0]["supportsAllDrives"] is True
    assert calls[0]["includeItemsFromAllDrives"] is True
    assert calls[1]["q"].endswith("sharedWithMe=true")
    assert calls[2]["corpora"] == "drive"
    assert calls[2]["driveId"] == "driveA"
    assert calls[3]["corpora"] == "drive"
    assert calls[3]["driveId"] == "driveB"


def test_list_docs_dedupes_ids(monkeypatch):
    """Duplicate IDs across queries should be deduplicated."""
    from chief_of_staff.config import settings

    monkeypatch.setattr(settings, "google_shared_drive_ids", "driveA")

    responses = [
        {"files": [{"id": "doc-1", "name": "A"}]},  # allDrives base query
        {"files": [{"id": "doc-1", "name": "A (dup)"}]},  # sharedWithMe duplicate
        {"files": [{"id": "doc-1", "name": "A (dup2)"}]},  # drive duplicate
    ]

    class _Files:
        def list(self, **kwargs):
            resp = responses.pop(0)
            return SimpleNamespace(execute=lambda: resp)

    drive = SimpleNamespace(files=lambda: _Files())
    files = _list_docs_from_drive(drive=drive, folder_id=None, max_results=10)

    assert len(files) == 1
    assert files[0]["id"] == "doc-1"


def test_list_accessible_shared_drive_ids_pages():
    """Shared drive discovery should paginate and collect IDs."""
    calls: list[dict] = []
    responses = [
        {"drives": [{"id": "driveA", "name": "A"}], "nextPageToken": "next"},
        {"drives": [{"id": "driveB", "name": "B"}]},
    ]

    class _Drives:
        def list(self, **kwargs):
            calls.append(kwargs)
            resp = responses.pop(0)
            return SimpleNamespace(execute=lambda: resp)

    drive = SimpleNamespace(drives=lambda: _Drives())
    ids = _list_accessible_shared_drive_ids(drive)

    assert ids == ["driveA", "driveB"]
    assert calls[0].get("pageToken") is None
    assert calls[1]["pageToken"] == "next"


def test_list_docs_merges_configured_and_discovered_drive_ids(monkeypatch):
    """Configured and discovered shared drive IDs should both be scanned once."""
    from chief_of_staff.config import settings

    monkeypatch.setattr(settings, "google_shared_drive_ids", "driveA")

    calls: list[dict] = []
    responses = [
        {"files": []},  # allDrives base query
        {"files": []},  # allDrives sharedWithMe query
        {"files": [{"id": "doc-a", "name": "A"}]},  # driveA
        {"files": [{"id": "doc-b", "name": "B"}]},  # driveB (discovered)
    ]

    class _Files:
        def list(self, **kwargs):
            calls.append(kwargs)
            resp = responses.pop(0)
            return SimpleNamespace(execute=lambda: resp)

    drive = SimpleNamespace(files=lambda: _Files())
    monkeypatch.setattr(
        "chief_of_staff.ingestion.gdocs._list_accessible_shared_drive_ids",
        lambda _drive: ["driveA", "driveB"],
    )

    files = _list_docs_from_drive(drive=drive, folder_id=None, max_results=10)
    per_drive_calls = [c for c in calls if c.get("corpora") == "drive"]

    assert len(files) == 2
    assert sorted([c["driveId"] for c in per_drive_calls]) == ["driveA", "driveB"]
