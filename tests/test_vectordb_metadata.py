"""Tests for vector metadata sanitization."""

from __future__ import annotations

from chief_of_staff.knowledge.vectordb import _sanitize_metadata


def test_sanitize_metadata_converts_complex_values():
    meta = {
        "title": "Doc",
        "owners": ["A", "B"],
        "flags": {"shared": True},
        "score": 1.2,
        "ok": True,
    }
    out = _sanitize_metadata(meta)
    assert out["title"] == "Doc"
    assert out["score"] == 1.2
    assert out["ok"] is True
    assert isinstance(out["owners"], str)
    assert isinstance(out["flags"], str)
