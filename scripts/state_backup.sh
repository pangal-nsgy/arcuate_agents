#!/usr/bin/env bash
set -euo pipefail

STATE_DIR_INPUT="${1:-${STATE_DIR:-$HOME/.arcuate_agents}}"
STATE_DIR_RESOLVED="${STATE_DIR_INPUT/#\~/$HOME}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT_PATH="${2:-./backups/arcuate-state-${STAMP}.tar.gz}"

mkdir -p "$(dirname "$OUTPUT_PATH")"
mkdir -p "$STATE_DIR_RESOLVED"

tar -czf "$OUTPUT_PATH" -C "$STATE_DIR_RESOLVED" .
echo "Backup written: $OUTPUT_PATH"
