#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "${PREFUND_SKIP_STATE_DRILL:-0}" != "1" ]]; then
  echo "[prefund] running state backup/restore drill..."
  bash scripts/state_drill.sh
fi

echo "[prefund] running parity-focused tests..."
PYTHONPATH=src pytest -q \
  tests/test_gateway_hooks_and_tools.py \
  tests/test_bluebubbles_webhook.py \
  tests/test_control_commands.py \
  tests/test_voice_commands.py

if [[ -n "${BASE_URL:-}" ]]; then
  echo "[prefund] running staging HTTP smoke checks against ${BASE_URL}"

  if [[ -z "${GATEWAY_AUTH_TOKEN:-}" ]]; then
    echo "[prefund] ERROR: GATEWAY_AUTH_TOKEN is required when BASE_URL is set"
    exit 1
  fi

  if [[ -z "${HOOKS_TOKEN:-}" ]]; then
    echo "[prefund] ERROR: HOOKS_TOKEN is required when BASE_URL is set"
    exit 1
  fi

  curl -fsS "${BASE_URL}/health" >/dev/null

  curl -fsS -X POST "${BASE_URL}/tools/invoke" \
    -H "Authorization: Bearer ${GATEWAY_AUTH_TOKEN}" \
    -H "Content-Type: application/json" \
    -d '{"action":"usage.status","sessionKey":"prefund","runId":"smoke","args":{}}' >/dev/null

  curl -fsS -X POST "${BASE_URL}/hooks/wake" \
    -H "Authorization: Bearer ${HOOKS_TOKEN}" \
    -H "Content-Type: application/json" \
    -d '{"text":"prefund-smoke","mode":"now"}' >/dev/null

  curl -fsS -X POST "${BASE_URL}/v1/chat/completions" \
    -H "Authorization: Bearer ${GATEWAY_AUTH_TOKEN}" \
    -H "Content-Type: application/json" \
    -d '{"model":"gpt-4.1","messages":[{"role":"user","content":"health ping"}]}' >/dev/null
fi

echo "[prefund] PASS"
