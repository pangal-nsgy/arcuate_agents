"""Persistent usage/cost budget ledger and circuit-breaker checks."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from datetime import datetime, UTC
from typing import Any

from chief_of_staff.config import settings


def _today_utc() -> str:
    return datetime.now(UTC).date().isoformat()


class UsageBudgetService:
    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._state: dict[str, Any] = {
            "version": 1,
            "day": _today_utc(),
            "daySpentUsd": 0.0,
            "sessions": {},
            "runs": {},
        }
        self._load_locked()

    def _load_locked(self) -> None:
        with self._lock:
            if not os.path.exists(self._path):
                return
            try:
                with open(self._path, encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception:
                return
            if not isinstance(payload, dict):
                return
            self._state = {
                "version": 1,
                "day": str(payload.get("day", _today_utc())),
                "daySpentUsd": float(payload.get("daySpentUsd", 0.0)),
                "sessions": payload.get("sessions", {}) if isinstance(payload.get("sessions"), dict) else {},
                "runs": payload.get("runs", {}) if isinstance(payload.get("runs"), dict) else {},
            }
            self._rollover_if_needed_locked()

    def _save_locked(self) -> None:
        directory = os.path.dirname(self._path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="usage-ledger-", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp, self._path)
        finally:
            try:
                os.remove(tmp)
            except FileNotFoundError:
                pass

    def _rollover_if_needed_locked(self) -> None:
        today = _today_utc()
        if self._state.get("day") == today:
            return
        self._state["day"] = today
        self._state["daySpentUsd"] = 0.0
        self._state["sessions"] = {}
        self._state["runs"] = {}
        self._save_locked()

    def _remaining(self, limit: float, spent: float) -> float | None:
        if limit <= 0:
            return None
        return round(limit - spent, 6)

    def status(self, session_key: str = "main", run_id: str = "default") -> dict[str, Any]:
        with self._lock:
            self._rollover_if_needed_locked()
            session_spent = float(self._state["sessions"].get(session_key, 0.0))
            run_spent = float(self._state["runs"].get(run_id, 0.0))
            day_spent = float(self._state.get("daySpentUsd", 0.0))
            return {
                "day": self._state["day"],
                "limitsUsd": {
                    "run": settings.usage_run_budget_usd,
                    "session": settings.usage_session_budget_usd,
                    "day": settings.usage_day_budget_usd,
                },
                "spentUsd": {
                    "run": round(run_spent, 6),
                    "session": round(session_spent, 6),
                    "day": round(day_spent, 6),
                },
                "remainingUsd": {
                    "run": self._remaining(settings.usage_run_budget_usd, run_spent),
                    "session": self._remaining(settings.usage_session_budget_usd, session_spent),
                    "day": self._remaining(settings.usage_day_budget_usd, day_spent),
                },
            }

    def cost(self) -> dict[str, Any]:
        with self._lock:
            self._rollover_if_needed_locked()
            return {
                "day": self._state["day"],
                "daySpentUsd": round(float(self._state.get("daySpentUsd", 0.0)), 6),
                "sessionCount": len(self._state.get("sessions", {})),
                "runCount": len(self._state.get("runs", {})),
                "sessions": copy.deepcopy(self._state.get("sessions", {})),
                "runs": copy.deepcopy(self._state.get("runs", {})),
            }

    def check_and_consume(
        self,
        session_key: str,
        run_id: str,
        cost_usd: float,
        reason: str,
    ) -> dict[str, Any]:
        if cost_usd < 0:
            raise ValueError("cost_usd must be non-negative")
        with self._lock:
            self._rollover_if_needed_locked()
            day_spent = float(self._state.get("daySpentUsd", 0.0))
            session_spent = float(self._state["sessions"].get(session_key, 0.0))
            run_spent = float(self._state["runs"].get(run_id, 0.0))

            next_day = day_spent + cost_usd
            next_session = session_spent + cost_usd
            next_run = run_spent + cost_usd

            if settings.usage_day_budget_usd > 0 and next_day > settings.usage_day_budget_usd:
                return {"allowed": False, "scope": "day", "reason": reason}
            if settings.usage_session_budget_usd > 0 and next_session > settings.usage_session_budget_usd:
                return {"allowed": False, "scope": "session", "reason": reason}
            if settings.usage_run_budget_usd > 0 and next_run > settings.usage_run_budget_usd:
                return {"allowed": False, "scope": "run", "reason": reason}

            self._state["daySpentUsd"] = round(next_day, 6)
            self._state["sessions"][session_key] = round(next_session, 6)
            self._state["runs"][run_id] = round(next_run, 6)
            self._save_locked()
            return {"allowed": True}


_service: UsageBudgetService | None = None
_service_lock = threading.Lock()


def get_usage_budget_service() -> UsageBudgetService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = UsageBudgetService(settings.usage_ledger_path)
    return _service


def reset_usage_budget_service_for_tests() -> None:
    global _service
    with _service_lock:
        _service = None
