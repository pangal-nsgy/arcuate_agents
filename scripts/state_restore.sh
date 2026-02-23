#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <backup-tar-gz> [state-dir]" >&2
  exit 1
fi

BACKUP_PATH="$1"
if [[ ! -f "$BACKUP_PATH" ]]; then
  echo "backup file not found: $BACKUP_PATH" >&2
  exit 1
fi

STATE_DIR_INPUT="${2:-${STATE_DIR:-$HOME/.arcuate_agents}}"
STATE_DIR_RESOLVED="${STATE_DIR_INPUT/#\~/$HOME}"
mkdir -p "$STATE_DIR_RESOLVED"

tar -xzf "$BACKUP_PATH" -C "$STATE_DIR_RESOLVED"
echo "State restored into: $STATE_DIR_RESOLVED"
