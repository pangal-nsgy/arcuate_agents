"""Persistent pairing store for BlueBubbles sender approval flow."""

from __future__ import annotations

import copy
import json
import os
import secrets
import tempfile
import threading
import time
from typing import Any

from chief_of_staff.config import settings


class BlueBubblesPairingStore:
    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._state: dict[str, Any] = {"version": 1, "paired": [], "pending": {}}
        self._load_locked()

    def _load_locked(self) -> None:
        with self._lock:
            if not os.path.exists(self._path):
                return
            try:
                with open(self._path, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                return
            if isinstance(data, dict):
                paired = data.get("paired", [])
                pending = data.get("pending", {})
                self._state = {
                    "version": 1,
                    "paired": [str(v).strip() for v in paired if str(v).strip()] if isinstance(paired, list) else [],
                    "pending": pending if isinstance(pending, dict) else {},
                }
                self._cleanup_locked()

    def _save_locked(self) -> None:
        directory = os.path.dirname(self._path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="bluebubbles-pairing-", suffix=".json", dir=directory)
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

    def _cleanup_locked(self) -> None:
        ttl_ms = max(int(settings.bluebubbles_pairing_code_ttl_minutes), 1) * 60 * 1000
        now = int(time.time() * 1000)
        pending = self._state.get("pending", {})
        to_delete: list[str] = []
        for code, record in pending.items():
            created = int(record.get("createdAtMs", 0))
            if created <= 0 or (now - created) > ttl_ms:
                to_delete.append(code)
        for code in to_delete:
            pending.pop(code, None)
        if to_delete:
            self._save_locked()

    def is_paired(self, sender: str) -> bool:
        sender_key = sender.strip()
        if not sender_key:
            return False
        with self._lock:
            self._cleanup_locked()
            return sender_key in set(self._state.get("paired", []))

    def request(self, sender: str) -> str:
        sender_key = sender.strip()
        if not sender_key:
            raise ValueError("sender is required")
        with self._lock:
            self._cleanup_locked()
            for code, record in self._state["pending"].items():
                if str(record.get("sender", "")).strip() == sender_key:
                    return code
            code = secrets.token_hex(3).upper()
            self._state["pending"][code] = {
                "sender": sender_key,
                "createdAtMs": int(time.time() * 1000),
            }
            self._save_locked()
            return code

    def list_pending(self) -> list[dict[str, str]]:
        with self._lock:
            self._cleanup_locked()
            items: list[dict[str, str]] = []
            for code, record in self._state.get("pending", {}).items():
                items.append({"code": str(code), "sender": str(record.get("sender", ""))})
            return items

    def list_paired(self) -> list[str]:
        with self._lock:
            self._cleanup_locked()
            return list(self._state.get("paired", []))

    def approve(self, code: str) -> str | None:
        code_key = code.strip().upper()
        if not code_key:
            return None
        with self._lock:
            self._cleanup_locked()
            record = self._state.get("pending", {}).pop(code_key, None)
            if not record:
                return None
            sender = str(record.get("sender", "")).strip()
            if not sender:
                self._save_locked()
                return None
            paired = set(self._state.get("paired", []))
            paired.add(sender)
            self._state["paired"] = sorted(paired)
            self._save_locked()
            return sender

    def deny(self, code: str) -> str | None:
        code_key = code.strip().upper()
        if not code_key:
            return None
        with self._lock:
            self._cleanup_locked()
            record = self._state.get("pending", {}).pop(code_key, None)
            if record is None:
                return None
            self._save_locked()
            return str(record.get("sender", "")).strip() or None

    def unpair(self, sender: str) -> bool:
        sender_key = sender.strip()
        if not sender_key:
            return False
        with self._lock:
            self._cleanup_locked()
            paired = set(self._state.get("paired", []))
            if sender_key not in paired:
                return False
            paired.remove(sender_key)
            self._state["paired"] = sorted(paired)
            self._save_locked()
            return True

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._cleanup_locked()
            return copy.deepcopy(self._state)


_store: BlueBubblesPairingStore | None = None
_store_lock = threading.Lock()


def get_bluebubbles_pairing_store() -> BlueBubblesPairingStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = BlueBubblesPairingStore(settings.bluebubbles_pairing_store_path)
    return _store


def reset_bluebubbles_pairing_store_for_tests() -> None:
    global _store
    with _store_lock:
        _store = None
