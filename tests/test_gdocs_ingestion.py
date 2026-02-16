"""Tests for Google Docs/Drive ingestion behavior."""

from __future__ import annotations

from types import SimpleNamespace

from chief_of_staff.ingestion.gdocs import _list_docs_from_drive


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
