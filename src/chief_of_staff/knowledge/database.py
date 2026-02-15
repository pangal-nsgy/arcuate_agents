"""SQLite database for structured metadata — clients, documents, conversations."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator

from chief_of_staff.config import settings

_DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,          -- 'gmail', 'gdocs', 'elevenlabs', 'meeting'
    source_id TEXT NOT NULL,       -- external ID from the source system
    title TEXT,
    content_preview TEXT,          -- first ~500 chars
    metadata TEXT,                 -- JSON blob for source-specific data
    ingested_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source, source_id)
);

CREATE TABLE IF NOT EXISTS clients (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    practice_name TEXT,
    email TEXT,
    phone TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    founder_phone TEXT NOT NULL,
    direction TEXT NOT NULL,       -- 'inbound' or 'outbound'
    message TEXT NOT NULL,
    response TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'in_progress', 'completed', 'failed'
    result TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS email_conversations (
    id TEXT PRIMARY KEY,
    email_address TEXT NOT NULL,
    thread_id TEXT,
    gmail_message_id TEXT UNIQUE,
    rfc_message_id TEXT,
    direction TEXT NOT NULL,
    subject TEXT,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_email_conv_thread ON email_conversations(thread_id);
CREATE INDEX IF NOT EXISTS idx_email_conv_addr ON email_conversations(email_address);
CREATE INDEX IF NOT EXISTS idx_email_conv_created ON email_conversations(created_at);

CREATE TABLE IF NOT EXISTS processed_gmail_events (
    gmail_message_id TEXT PRIMARY KEY,
    processed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS complaints (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    sender TEXT NOT NULL,
    thread_id TEXT,
    severity TEXT NOT NULL DEFAULT 'medium',
    summary TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);
"""


def init_db() -> None:
    """Initialize the database schema."""
    db_path = Path(settings.sqlite_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _get_conn() as conn:
        conn.executescript(_DB_SCHEMA)


@contextmanager
def _get_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(settings.sqlite_db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_document(
    doc_id: str,
    source: str,
    source_id: str,
    title: str = "",
    content_preview: str = "",
    metadata: str = "{}",
) -> None:
    """Insert or update a document record."""
    now = datetime.utcnow().isoformat()
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO documents (id, source, source_id, title, content_preview, metadata, ingested_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, source_id) DO UPDATE SET
                title=excluded.title,
                content_preview=excluded.content_preview,
                metadata=excluded.metadata,
                updated_at=excluded.updated_at
            """,
            (doc_id, source, source_id, title, content_preview, metadata, now, now),
        )


def log_conversation(
    conv_id: str, founder_phone: str, direction: str, message: str, response: str | None = None
) -> None:
    """Log an SMS conversation turn."""
    now = datetime.utcnow().isoformat()
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO conversations (id, founder_phone, direction, message, response, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (conv_id, founder_phone, direction, message, response, now),
        )


def get_recent_conversations(founder_phone: str, limit: int = 20) -> list[dict[str, Any]]:
    """Get recent conversation history with a founder."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE founder_phone = ? ORDER BY created_at DESC LIMIT ?",
            (founder_phone, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def search_documents(query: str, source: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    """Simple text search across document titles and previews."""
    with _get_conn() as conn:
        if source:
            rows = conn.execute(
                "SELECT * FROM documents WHERE source = ? AND (title LIKE ? OR content_preview LIKE ?) ORDER BY updated_at DESC LIMIT ?",
                (source, f"%{query}%", f"%{query}%", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM documents WHERE title LIKE ? OR content_preview LIKE ? ORDER BY updated_at DESC LIMIT ?",
                (f"%{query}%", f"%{query}%", limit),
            ).fetchall()
    return [dict(r) for r in rows]


def log_email_conversation(
    conv_id: str,
    email_address: str,
    direction: str,
    body: str,
    thread_id: str = "",
    gmail_message_id: str = "",
    rfc_message_id: str = "",
    subject: str = "",
) -> None:
    """Log an email conversation turn. Skips silently on duplicate gmail_message_id."""
    now = datetime.utcnow().isoformat()
    with _get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO email_conversations
            (id, email_address, thread_id, gmail_message_id, rfc_message_id, direction, subject, body, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (conv_id, email_address, thread_id, gmail_message_id, rfc_message_id, direction, subject, body, now),
        )


def get_email_thread(thread_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Fetch email conversation history for a thread, ordered by time."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM email_conversations WHERE thread_id = ? ORDER BY created_at ASC LIMIT ?",
            (thread_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def is_gmail_message_processed(gmail_message_id: str) -> bool:
    """Check if a Gmail message has already been processed (idempotency)."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM processed_gmail_events WHERE gmail_message_id = ?",
            (gmail_message_id,),
        ).fetchone()
    return row is not None


def mark_gmail_message_processed(gmail_message_id: str) -> None:
    """Mark a Gmail message as processed."""
    now = datetime.utcnow().isoformat()
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO processed_gmail_events (gmail_message_id, processed_at) VALUES (?, ?)",
            (gmail_message_id, now),
        )


def try_claim_gmail_message(gmail_message_id: str) -> bool:
    """Atomically claim a Gmail message for processing.

    Returns True if this caller won the claim, False if already claimed.
    Uses INSERT OR IGNORE + rowcount to avoid check-then-mark races.
    """
    now = datetime.utcnow().isoformat()
    with _get_conn() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO processed_gmail_events (gmail_message_id, processed_at) VALUES (?, ?)",
            (gmail_message_id, now),
        )
        return cursor.rowcount > 0


def unclaim_gmail_message(gmail_message_id: str) -> None:
    """Release a claim on a Gmail message so it can be retried on transient failure."""
    with _get_conn() as conn:
        conn.execute(
            "DELETE FROM processed_gmail_events WHERE gmail_message_id = ?",
            (gmail_message_id,),
        )


def log_complaint(
    complaint_id: str,
    source: str,
    sender: str,
    summary: str,
    thread_id: str = "",
    severity: str = "medium",
) -> None:
    """Persist a complaint for future supervised review."""
    now = datetime.utcnow().isoformat()
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO complaints (id, source, sender, thread_id, severity, summary, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'open', ?)""",
            (complaint_id, source, sender, thread_id, severity, summary, now),
        )


def get_open_complaints(limit: int = 50) -> list[dict[str, Any]]:
    """Get open complaints for review."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM complaints WHERE status = 'open' ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
