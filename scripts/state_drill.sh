#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

TMP_ROOT="$(mktemp -d)"
STATE_DIR="$TMP_ROOT/state"
BACKUP_PATH="$TMP_ROOT/state-backup.tar.gz"
export STATE_DIR
export SQLITE_DB_PATH="chief_of_staff.db"
export EXEC_APPROVALS_PATH="exec-approvals.json"
export USAGE_LEDGER_PATH="usage-ledger.json"
export BLUEBUBBLES_PAIRING_STORE_PATH="bluebubbles-pairing.json"

cleanup() {
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT

mkdir -p "$STATE_DIR"
cat >"$STATE_DIR/exec-approvals.json" <<'JSON'
{"policy":{"execEnabled":false,"requireApprovalByDefault":true},"allowlists":{}}
JSON
cat >"$STATE_DIR/usage-ledger.json" <<'JSON'
{"entries":[]}
JSON
cat >"$STATE_DIR/bluebubbles-pairing.json" <<'JSON'
{"pending":{},"paired":{}}
JSON

PYTHONPATH=src python3 - <<'PY'
import sqlite3
from chief_of_staff.knowledge.database import init_db, log_conversation
from chief_of_staff.config import settings

init_db()
log_conversation("drill-1", "+15555550123", "inbound", "state drill")
conn = sqlite3.connect(settings.sqlite_db_path)
count = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
conn.close()
if count < 1:
    raise SystemExit("conversation seed failed")
PY

bash scripts/state_backup.sh "$STATE_DIR" "$BACKUP_PATH" >/dev/null
rm -rf "$STATE_DIR"
mkdir -p "$STATE_DIR"
bash scripts/state_restore.sh "$BACKUP_PATH" "$STATE_DIR" >/dev/null

PYTHONPATH=src python3 - <<'PY'
import os
import sqlite3
from chief_of_staff.config import settings

required = [
    settings.sqlite_db_path,
    settings.exec_approvals_path,
    settings.usage_ledger_path,
    settings.bluebubbles_pairing_store_path,
]
for path in required:
    if not os.path.exists(path):
        raise SystemExit(f"missing restored path: {path}")
conn = sqlite3.connect(settings.sqlite_db_path)
count = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
conn.close()
if count < 1:
    raise SystemExit("restored sqlite verification failed")
PY

echo "[state-drill] PASS"
