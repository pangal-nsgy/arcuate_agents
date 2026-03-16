#!/usr/bin/env bash
# Fetch runtime logs from Render for the preopcaller services.
# Usage:
#   ./scripts/render-logs.sh              # last 50 lines from preopcaller-api
#   ./scripts/render-logs.sh 100          # last 100 lines
#   ./scripts/render-logs.sh 50 scheduler # from preopcaller-scheduler
#   ./scripts/render-logs.sh 50 api error # only error-level logs
#   ./scripts/render-logs.sh 50 api all 2h  # last 2 hours

set -euo pipefail

RENDER_API_KEY="${RENDER_API_KEY:-rnd_wl8YD8IaGFpWzPta82lF21jEKUNH}"
OWNER_ID="tea-d4r2p8e3jp1c739q4s30"

# Service IDs
API_SVC="srv-d4r2t63e5dus73f1p6mg"
SCHEDULER_SVC="srv-d4r4h2er433s738husu0"

LIMIT="${1:-50}"
SERVICE="${2:-api}"
LEVEL="${3:-all}"
TIME_RANGE="${4:-}"

case "$SERVICE" in
  api)       SVC_ID="$API_SVC" ;;
  scheduler) SVC_ID="$SCHEDULER_SVC" ;;
  *)         echo "Unknown service: $SERVICE (use 'api' or 'scheduler')"; exit 1 ;;
esac

# Build URL
URL="https://api.render.com/v1/logs?ownerId=${OWNER_ID}&resource=${SVC_ID}&direction=backward&limit=${LIMIT}"

# Add time range if specified (e.g. "2h", "30m", "1d")
if [[ -n "$TIME_RANGE" ]]; then
  if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS date
    case "$TIME_RANGE" in
      *h) SECS=$(( ${TIME_RANGE%h} * 3600 )) ;;
      *m) SECS=$(( ${TIME_RANGE%m} * 60 )) ;;
      *d) SECS=$(( ${TIME_RANGE%d} * 86400 )) ;;
      *)  SECS=3600 ;;
    esac
    START_TIME=$(date -u -v-${SECS}S +"%Y-%m-%dT%H:%M:%SZ")
  else
    START_TIME=$(date -u -d "-${TIME_RANGE}" +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || true)
  fi
  if [[ -n "${START_TIME:-}" ]]; then
    URL="${URL}&startTime=${START_TIME}"
  fi
fi

# Fetch and format
curl -s \
  -H "Authorization: Bearer ${RENDER_API_KEY}" \
  -H "Accept: application/json" \
  "$URL" | python3 -c "
import json, sys
from datetime import datetime

data = json.load(sys.stdin)
if 'logs' not in data:
    print(json.dumps(data, indent=2))
    sys.exit(1)

level_filter = '${LEVEL}'
logs = data['logs']
# Reverse so oldest is first (we fetched backward)
logs.reverse()

for entry in logs:
    labels = {l['name']: l['value'] for l in entry.get('labels', [])}
    lvl = labels.get('level', 'info')

    if level_filter != 'all' and lvl != level_filter:
        continue

    msg = entry.get('message', '').rstrip()
    if not msg:
        continue

    ts = entry.get('timestamp', '')
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        ts_short = dt.strftime('%H:%M:%S')
    except:
        ts_short = ts[:19]

    lvl_tag = '' if lvl == 'info' else f' [{lvl.upper()}]'
    print(f'{ts_short}{lvl_tag}  {msg}')

has_more = data.get('hasMore', False)
if has_more:
    print(f'\\n--- has more logs (use higher limit or narrower time range) ---')
"
