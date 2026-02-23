from __future__ import annotations

import sqlite3
from pathlib import Path

from chief_of_staff.config import Settings, settings
from chief_of_staff.knowledge.database import init_db


def test_settings_resolve_relative_paths_under_state_dir(tmp_path: Path) -> None:
    cfg = Settings(
        _env_file=None,
        state_dir=str(tmp_path),
        sqlite_db_path="chief_of_staff.db",
        exec_approvals_path="exec-approvals.json",
        usage_ledger_path="usage-ledger.json",
        bluebubbles_pairing_store_path="bluebubbles-pairing.json",
    )

    assert cfg.sqlite_db_path == str(tmp_path / "chief_of_staff.db")
    assert cfg.exec_approvals_path == str(tmp_path / "exec-approvals.json")
    assert cfg.usage_ledger_path == str(tmp_path / "usage-ledger.json")
    assert cfg.bluebubbles_pairing_store_path == str(tmp_path / "bluebubbles-pairing.json")


def test_init_db_applies_schema_migrations_and_wal_mode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "state.db"
    monkeypatch.setattr(settings, "sqlite_db_path", str(db_path))

    init_db()
    init_db()

    with sqlite3.connect(str(db_path)) as conn:
        migration_count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        has_documents_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='documents'"
        ).fetchone()

    assert migration_count >= 1
    assert str(journal_mode).lower() == "wal"
    assert has_documents_table is not None

