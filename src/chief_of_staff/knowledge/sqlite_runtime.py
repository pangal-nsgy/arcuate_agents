"""SQLite runtime connection policy for local host persistence."""

from __future__ import annotations

import sqlite3


def configure_sqlite_connection(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Apply runtime-safe SQLite settings for concurrent local access."""
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

