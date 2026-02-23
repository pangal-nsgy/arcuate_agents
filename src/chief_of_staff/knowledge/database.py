"""SQLite database for structured metadata — clients, documents, conversations."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Generator

from chief_of_staff.config import settings
from chief_of_staff.knowledge.sqlite_runtime import configure_sqlite_connection

_MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def init_db() -> None:
    """Initialize the database schema."""
    db_path = Path(settings.sqlite_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _get_conn() as conn:
        _apply_migrations(conn)


@contextmanager
def _get_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = configure_sqlite_connection(sqlite3.connect(settings.sqlite_db_path))
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migration_files() -> list[Path]:
    if not _MIGRATIONS_DIR.exists():
        return []
    return sorted(
        (
            path for path in _MIGRATIONS_DIR.iterdir()
            if path.is_file() and path.suffix == ".sql"
        ),
        key=lambda path: path.name,
    )


def _apply_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
            id TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )"""
    )

    applied = {
        row["id"]
        for row in conn.execute("SELECT id FROM schema_migrations").fetchall()
    }
    for migration_path in _migration_files():
        migration_id = migration_path.name
        if migration_id in applied:
            continue
        conn.executescript(migration_path.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO schema_migrations (id, applied_at) VALUES (?, ?)",
            (migration_id, datetime.utcnow().isoformat()),
        )


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


def create_scheduled_action(
    action_id: str,
    action_type: str,
    schedule_type: str,
    schedule_time: str,
    channel: str,
    target: str,
    prompt: str,
) -> None:
    """Create a new scheduled action."""
    now = datetime.utcnow().isoformat()
    # Compute initial next_run_at
    next_run = _compute_next_run(schedule_type, schedule_time, now)
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO scheduled_actions
            (id, action_type, schedule_type, schedule_time, channel, target, prompt, status, next_run_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
            (action_id, action_type, schedule_type, schedule_time, channel, target, prompt, next_run, now),
        )


def get_due_actions(now_iso: str) -> list[dict[str, Any]]:
    """Get scheduled actions that are due for execution."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM scheduled_actions WHERE status = 'active' AND next_run_at <= ? ORDER BY next_run_at ASC",
            (now_iso,),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_action_run(action_id: str, now_iso: str) -> None:
    """Mark a scheduled action as run and compute next execution time."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT schedule_type, schedule_time FROM scheduled_actions WHERE id = ?",
            (action_id,),
        ).fetchone()
        if not row:
            return
        schedule_type = row["schedule_type"]
        schedule_time = row["schedule_time"]

        if schedule_type == "once":
            conn.execute(
                "UPDATE scheduled_actions SET last_run_at = ?, status = 'completed' WHERE id = ?",
                (now_iso, action_id),
            )
        else:
            next_run = _compute_next_run(schedule_type, schedule_time, now_iso)
            conn.execute(
                "UPDATE scheduled_actions SET last_run_at = ?, next_run_at = ? WHERE id = ?",
                (now_iso, next_run, action_id),
            )


def seed_default_actions() -> None:
    """Insert default scheduled actions (idempotent — uses INSERT OR IGNORE)."""
    now = datetime.utcnow().isoformat()
    defaults = [
        ("default_daily_briefing", "daily_briefing", "daily", "13:00", "discord", "daily-briefing", "Generate daily briefing"),
        ("default_weekly_pulse", "weekly_pulse", "weekly", "14:00", "discord", "team-health", "Generate weekly team health pulse"),
        ("default_engagement_check", "engagement_check", "daily", "13:00", "discord", "", "Check team engagement"),
    ]
    with _get_conn() as conn:
        for action_id, action_type, sched_type, sched_time, channel, target, prompt in defaults:
            next_run = _compute_next_run(sched_type, sched_time, now)
            conn.execute(
                """INSERT OR IGNORE INTO scheduled_actions
                (id, action_type, schedule_type, schedule_time, channel, target, prompt, status, next_run_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
                (action_id, action_type, sched_type, sched_time, channel, target, prompt, next_run, now),
            )


def _compute_next_run(schedule_type: str, schedule_time: str, after_iso: str) -> str:
    """Compute the next run time for a scheduled action.

    For 'daily': next occurrence of schedule_time (HH:MM) after the given time.
    For 'weekly': next Monday at schedule_time after the given time.
    For 'once': schedule_time is already a full ISO datetime.
    """
    if schedule_type == "once":
        return schedule_time

    # Parse the "after" time
    try:
        after = datetime.fromisoformat(after_iso)
    except ValueError:
        after = datetime.utcnow()

    # Parse HH:MM
    parts = schedule_time.split(":")
    hour = int(parts[0]) if len(parts) >= 1 else 0
    minute = int(parts[1]) if len(parts) >= 2 else 0

    if schedule_type == "daily":
        candidate = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= after:
            candidate += timedelta(days=1)
        return candidate.isoformat()

    if schedule_type == "weekly":
        # Next Monday
        days_until_monday = (7 - after.weekday()) % 7
        if days_until_monday == 0:
            candidate = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= after:
                days_until_monday = 7
            else:
                return candidate.isoformat()
        candidate = (after + timedelta(days=days_until_monday)).replace(
            hour=hour, minute=minute, second=0, microsecond=0,
        )
        return candidate.isoformat()

    return after.isoformat()


def create_sub_agent_run(
    run_id: str,
    parent_agent: str,
    child_agent: str,
    task: str,
    requester_channel: str = "",
    requester_user_id: str = "",
    requester_session_id: str = "",
) -> None:
    """Create a new durable sub-agent run record."""
    now = datetime.utcnow().isoformat()
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO sub_agent_runs
            (id, parent_agent, child_agent, task, status, requester_channel, requester_user_id, requester_session_id, created_at)
            VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?)""",
            (
                run_id,
                parent_agent,
                child_agent,
                task,
                requester_channel,
                requester_user_id,
                requester_session_id,
                now,
            ),
        )


def mark_sub_agent_run_running(run_id: str) -> None:
    """Mark a sub-agent run as running."""
    now = datetime.utcnow().isoformat()
    with _get_conn() as conn:
        conn.execute(
            "UPDATE sub_agent_runs SET status = 'running', started_at = ? WHERE id = ?",
            (now, run_id),
        )


def mark_sub_agent_run_completed(run_id: str, result: str) -> None:
    """Mark a sub-agent run as completed."""
    now = datetime.utcnow().isoformat()
    with _get_conn() as conn:
        conn.execute(
            "UPDATE sub_agent_runs SET status = 'completed', result = ?, ended_at = ? WHERE id = ?",
            (result[:8000], now, run_id),
        )


def mark_sub_agent_run_failed(run_id: str, error: str) -> None:
    """Mark a sub-agent run as failed."""
    now = datetime.utcnow().isoformat()
    with _get_conn() as conn:
        conn.execute(
            "UPDATE sub_agent_runs SET status = 'failed', error = ?, ended_at = ? WHERE id = ?",
            (error[:4000], now, run_id),
        )


def mark_sub_agent_run_cancelled(run_id: str, reason: str = "") -> None:
    """Mark a sub-agent run as cancelled."""
    now = datetime.utcnow().isoformat()
    with _get_conn() as conn:
        conn.execute(
            "UPDATE sub_agent_runs SET status = 'cancelled', error = ?, ended_at = ? WHERE id = ?",
            (reason[:4000], now, run_id),
        )


def get_sub_agent_run(run_id: str) -> dict[str, Any] | None:
    """Get a sub-agent run by ID."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM sub_agent_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
    return dict(row) if row else None


def list_sub_agent_runs(
    parent_agent: str = "",
    status: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List sub-agent runs with optional filters."""
    query = "SELECT * FROM sub_agent_runs WHERE 1=1"
    params: list[Any] = []
    if parent_agent:
        query += " AND parent_agent = ?"
        params.append(parent_agent)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with _get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]
