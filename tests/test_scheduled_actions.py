"""Tests for scheduled action infrastructure."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest


class TestScheduledActionsCRUD:
    """CRUD operations for scheduled_actions table."""

    def test_create_and_get_due(self, tmp_path):
        """Created action appears in get_due_actions when due."""
        db_path = str(tmp_path / "test.db")
        with patch("chief_of_staff.knowledge.database.settings") as mock_settings:
            mock_settings.sqlite_db_path = db_path
            from chief_of_staff.knowledge.database import (
                init_db, create_scheduled_action, get_due_actions,
            )
            init_db()

            # Create action with next_run_at in the past
            create_scheduled_action(
                action_id="act_1",
                action_type="daily_briefing",
                schedule_type="daily",
                schedule_time="13:00",
                channel="discord",
                target="daily-briefing",
                prompt="Generate briefing",
            )

            # It should be due now (next_run_at was computed as next 13:00)
            far_future = (datetime.utcnow() + timedelta(days=2)).isoformat()
            due = get_due_actions(far_future)
            assert len(due) >= 1
            assert due[0]["action_type"] == "daily_briefing"

    def test_get_due_filters_future_actions(self, tmp_path):
        """Actions with next_run_at in the future are not returned."""
        db_path = str(tmp_path / "test.db")
        with patch("chief_of_staff.knowledge.database.settings") as mock_settings:
            mock_settings.sqlite_db_path = db_path
            from chief_of_staff.knowledge.database import (
                init_db, create_scheduled_action, get_due_actions,
            )
            init_db()

            create_scheduled_action(
                action_id="act_future",
                action_type="custom",
                schedule_type="once",
                schedule_time=(datetime.utcnow() + timedelta(days=30)).isoformat(),
                channel="discord",
                target="test",
                prompt="Future action",
            )

            now = datetime.utcnow().isoformat()
            due = get_due_actions(now)
            future_ids = [a["id"] for a in due]
            assert "act_future" not in future_ids

    def test_mark_action_run_updates_last_run(self, tmp_path):
        """mark_action_run sets last_run_at and computes next_run_at."""
        db_path = str(tmp_path / "test.db")
        with patch("chief_of_staff.knowledge.database.settings") as mock_settings:
            mock_settings.sqlite_db_path = db_path
            from chief_of_staff.knowledge.database import (
                init_db, create_scheduled_action, mark_action_run, get_due_actions,
            )
            init_db()

            create_scheduled_action(
                action_id="act_mark",
                action_type="daily_briefing",
                schedule_type="daily",
                schedule_time="13:00",
                channel="discord",
                target="test",
                prompt="Test",
            )

            now = datetime.utcnow().isoformat()
            mark_action_run("act_mark", now)

            # After marking, action should not be due for at least ~23 hours
            slightly_later = (datetime.utcnow() + timedelta(hours=1)).isoformat()
            due = get_due_actions(slightly_later)
            due_ids = [a["id"] for a in due]
            assert "act_mark" not in due_ids

    def test_mark_once_action_completes(self, tmp_path):
        """One-time actions get status='completed' after running."""
        db_path = str(tmp_path / "test.db")
        with patch("chief_of_staff.knowledge.database.settings") as mock_settings:
            mock_settings.sqlite_db_path = db_path
            from chief_of_staff.knowledge.database import init_db, create_scheduled_action, mark_action_run, _get_conn
            init_db()

            create_scheduled_action(
                action_id="act_once",
                action_type="research",
                schedule_type="once",
                schedule_time=datetime.utcnow().isoformat(),
                channel="discord",
                target="test",
                prompt="Research something",
            )

            mark_action_run("act_once", datetime.utcnow().isoformat())

            with _get_conn() as conn:
                row = conn.execute("SELECT status FROM scheduled_actions WHERE id = ?", ("act_once",)).fetchone()
            assert row["status"] == "completed"

    def test_seed_default_actions_is_idempotent(self, tmp_path):
        """seed_default_actions can be called multiple times without error."""
        db_path = str(tmp_path / "test.db")
        with patch("chief_of_staff.knowledge.database.settings") as mock_settings:
            mock_settings.sqlite_db_path = db_path
            from chief_of_staff.knowledge.database import init_db, seed_default_actions, _get_conn
            init_db()

            seed_default_actions()
            seed_default_actions()  # Should not raise

            with _get_conn() as conn:
                count = conn.execute("SELECT COUNT(*) as c FROM scheduled_actions").fetchone()
            assert count["c"] == 3  # briefing, pulse, engagement check


class TestComputeNextRun:
    """Tests for _compute_next_run helper."""

    def test_once_returns_schedule_time(self):
        """Once actions return schedule_time as-is."""
        from chief_of_staff.knowledge.database import _compute_next_run
        result = _compute_next_run("once", "2026-03-01T10:00:00", "2026-02-15T00:00:00")
        assert result == "2026-03-01T10:00:00"

    def test_daily_returns_next_occurrence(self):
        """Daily actions return the next HH:MM occurrence."""
        from chief_of_staff.knowledge.database import _compute_next_run
        # If it's 14:00 and schedule is 13:00, next run should be tomorrow
        result = _compute_next_run("daily", "13:00", "2026-02-15T14:00:00")
        assert "2026-02-16T13:00:00" in result

    def test_daily_returns_today_if_not_passed(self):
        """Daily actions return today's time if not yet passed."""
        from chief_of_staff.knowledge.database import _compute_next_run
        result = _compute_next_run("daily", "23:59", "2026-02-15T00:00:00")
        assert "2026-02-15T23:59:00" in result

    def test_weekly_returns_next_monday(self):
        """Weekly actions return next Monday at the scheduled time."""
        from chief_of_staff.knowledge.database import _compute_next_run
        # 2026-02-15 is a Sunday
        result = _compute_next_run("weekly", "14:00", "2026-02-15T15:00:00")
        assert "2026-02-16" in result  # Monday Feb 16
        assert "14:00:00" in result
