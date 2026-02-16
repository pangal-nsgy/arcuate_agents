"""Activity tracking for all agent actions — logs to SQLite for the dashboard."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Generator

from chief_of_staff.config import settings

logger = logging.getLogger(__name__)

ACTIVITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_activity (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    session_id TEXT DEFAULT '',
    action_type TEXT NOT NULL,
    action_detail TEXT DEFAULT '',
    input_summary TEXT DEFAULT '',
    output_summary TEXT DEFAULT '',
    channel TEXT DEFAULT '',
    user_id TEXT DEFAULT '',
    duration_ms INTEGER DEFAULT 0,
    metadata TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_activity_timestamp ON agent_activity(timestamp);
CREATE INDEX IF NOT EXISTS idx_activity_agent ON agent_activity(agent_name);
CREATE INDEX IF NOT EXISTS idx_activity_type ON agent_activity(action_type);
"""

# Action types
MESSAGE_RECEIVED = "message_received"
MESSAGE_SENT = "message_sent"
TOOL_USE = "tool_use"
KNOWLEDGE_SEARCH = "knowledge_search"
WEB_SEARCH = "web_search"
CONFIG_UPDATE = "config_update"
MEMORY_WRITE = "memory_write"
MEMORY_READ = "memory_read"
SUB_AGENT_SPAWN = "sub_agent_spawn"
DELEGATION = "delegation"
ERROR = "error"
# Communication
SMS_RECEIVED = "sms_received"
SMS_SENT = "sms_sent"
# Ingestion
CALL_INGESTED = "call_ingested"
EMAIL_INGESTED = "email_ingested"
EMAIL_RECEIVED = "email_received"
EMAIL_SENT = "email_sent"
EMAIL_SKIPPED = "email_skipped"
DOC_INGESTED = "doc_ingested"
MEETING_INGESTED = "meeting_ingested"
INGESTION_SYNC = "ingestion_sync"
# Webhooks
WEBHOOK_RECEIVED = "webhook_received"
# Code self-modification
CODE_READ = "code_read"
CODE_EDIT = "code_edit"
CODE_DEPLOY = "code_deploy"
# Proactive features
SCHEDULED_ACTION_RUN = "scheduled_action_run"
BRIEFING_SENT = "briefing_sent"
MEETING_DEBRIEF = "meeting_debrief"
PRACTICE_RESEARCHED = "practice_researched"
TEAM_PULSE = "team_pulse"
ENGAGEMENT_ALERT = "engagement_alert"
CATCHUP_GENERATED = "catchup_generated"
# Execution
PYTHON_EXEC = "python_exec"
WEBPAGE_FETCH = "webpage_fetch"
PACKAGE_INSTALL = "package_install"
PROGRESS_REPORT = "progress_report"


def init_activity_tables() -> None:
    """Create activity tracking tables (called at startup)."""
    with _get_conn() as conn:
        conn.executescript(ACTIVITY_SCHEMA)
    logger.info("Activity tracking tables initialized")


@contextmanager
def _get_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(settings.sqlite_db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def log_activity(
    agent_name: str,
    action_type: str,
    action_detail: str = "",
    input_summary: str = "",
    output_summary: str = "",
    channel: str = "",
    user_id: str = "",
    session_id: str = "",
    duration_ms: int = 0,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Log an activity event. Returns the activity ID."""
    activity_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    meta_json = json.dumps(metadata or {})

    try:
        with _get_conn() as conn:
            conn.execute(
                """INSERT INTO agent_activity
                (id, timestamp, agent_name, session_id, action_type, action_detail,
                 input_summary, output_summary, channel, user_id, duration_ms, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    activity_id, now, agent_name, session_id, action_type,
                    action_detail, input_summary[:2000], output_summary[:2000],
                    channel, user_id, duration_ms, meta_json,
                ),
            )
    except Exception as e:
        logger.error(f"Failed to log activity: {e}")

    return activity_id


class ActivityTimer:
    """Context manager to time an operation and log it."""

    def __init__(self, agent_name: str, action_type: str, **kwargs):
        self.agent_name = agent_name
        self.action_type = action_type
        self.kwargs = kwargs
        self._start = 0.0

    def __enter__(self):
        self._start = time.time()
        return self

    def __exit__(self, *args):
        duration_ms = int((time.time() - self._start) * 1000)
        log_activity(
            agent_name=self.agent_name,
            action_type=self.action_type,
            duration_ms=duration_ms,
            **self.kwargs,
        )


def get_recent_activity(
    limit: int = 50,
    offset: int = 0,
    agent_name: str | None = None,
    action_type: str | None = None,
    since_hours: int | None = None,
) -> list[dict[str, Any]]:
    """Get recent activity with optional filters."""
    query = "SELECT * FROM agent_activity WHERE 1=1"
    params: list[Any] = []

    if agent_name:
        query += " AND agent_name = ?"
        params.append(agent_name)
    if action_type:
        query += " AND action_type = ?"
        params.append(action_type)
    if since_hours:
        cutoff = (datetime.utcnow() - timedelta(hours=since_hours)).isoformat()
        query += " AND timestamp >= ?"
        params.append(cutoff)

    query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with _get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_activity_stats(hours: int = 24) -> dict[str, Any]:
    """Get aggregate activity stats for the dashboard."""
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

    with _get_conn() as conn:
        # Counts by action type
        rows = conn.execute(
            "SELECT action_type, COUNT(*) as count FROM agent_activity WHERE timestamp >= ? GROUP BY action_type",
            (cutoff,),
        ).fetchall()
        by_type = {r["action_type"]: r["count"] for r in rows}

        # Total count
        total = conn.execute(
            "SELECT COUNT(*) as count FROM agent_activity WHERE timestamp >= ?",
            (cutoff,),
        ).fetchone()

        # Active agents
        agents = conn.execute(
            "SELECT DISTINCT agent_name FROM agent_activity WHERE timestamp >= ?",
            (cutoff,),
        ).fetchall()

        # All-time totals
        all_time = conn.execute("SELECT COUNT(*) as count FROM agent_activity").fetchone()

    return {
        "period_hours": hours,
        "total_actions": total["count"] if total else 0,
        "all_time_total": all_time["count"] if all_time else 0,
        "messages_received": by_type.get(MESSAGE_RECEIVED, 0),
        "messages_sent": by_type.get(MESSAGE_SENT, 0),
        "sms_received": by_type.get(SMS_RECEIVED, 0),
        "sms_sent": by_type.get(SMS_SENT, 0),
        "tool_uses": by_type.get(TOOL_USE, 0),
        "knowledge_searches": by_type.get(KNOWLEDGE_SEARCH, 0),
        "web_searches": by_type.get(WEB_SEARCH, 0),
        "config_updates": by_type.get(CONFIG_UPDATE, 0),
        "memory_writes": by_type.get(MEMORY_WRITE, 0),
        "memory_reads": by_type.get(MEMORY_READ, 0),
        "sub_agents_spawned": by_type.get(SUB_AGENT_SPAWN, 0),
        "delegations": by_type.get(DELEGATION, 0),
        "errors": by_type.get(ERROR, 0),
        "calls_ingested": by_type.get(CALL_INGESTED, 0),
        "emails_ingested": by_type.get(EMAIL_INGESTED, 0),
        "emails_received": by_type.get(EMAIL_RECEIVED, 0),
        "emails_sent": by_type.get(EMAIL_SENT, 0),
        "emails_skipped": by_type.get(EMAIL_SKIPPED, 0),
        "docs_ingested": by_type.get(DOC_INGESTED, 0),
        "meetings_ingested": by_type.get(MEETING_INGESTED, 0),
        "sync_cycles": by_type.get(INGESTION_SYNC, 0),
        "webhooks_received": by_type.get(WEBHOOK_RECEIVED, 0),
        "code_reads": by_type.get(CODE_READ, 0),
        "code_edits": by_type.get(CODE_EDIT, 0),
        "code_deploys": by_type.get(CODE_DEPLOY, 0),
        "python_execs": by_type.get(PYTHON_EXEC, 0),
        "webpage_fetches": by_type.get(WEBPAGE_FETCH, 0),
        "package_installs": by_type.get(PACKAGE_INSTALL, 0),
        "progress_reports": by_type.get(PROGRESS_REPORT, 0),
        "scheduled_actions": by_type.get(SCHEDULED_ACTION_RUN, 0),
        "briefings_sent": by_type.get(BRIEFING_SENT, 0),
        "meeting_debriefs": by_type.get(MEETING_DEBRIEF, 0),
        "practices_researched": by_type.get(PRACTICE_RESEARCHED, 0),
        "team_pulses": by_type.get(TEAM_PULSE, 0),
        "engagement_alerts": by_type.get(ENGAGEMENT_ALERT, 0),
        "catchups_generated": by_type.get(CATCHUP_GENERATED, 0),
        "active_agents": [r["agent_name"] for r in agents],
        "by_type": by_type,
    }


def get_agent_activity_summary() -> list[dict[str, Any]]:
    """Get per-agent activity summary."""
    with _get_conn() as conn:
        rows = conn.execute(
            """SELECT agent_name,
                      COUNT(*) as total_actions,
                      MAX(timestamp) as last_active,
                      SUM(CASE WHEN action_type = ? THEN 1 ELSE 0 END) as messages,
                      SUM(CASE WHEN action_type = ? THEN 1 ELSE 0 END) as tool_uses
               FROM agent_activity
               GROUP BY agent_name
               ORDER BY last_active DESC""",
            (MESSAGE_RECEIVED, TOOL_USE),
        ).fetchall()
    return [dict(r) for r in rows]
