# Non-Railway Sandbox Runbook (OpenClaw-Style)

OpenClaw reference: `https://github.com/openclaw/openclaw`

## Purpose
Run Arcuate gateway + worker on a host-local persistent state volume, independent of Railway.

## Prerequisites
- Docker + Docker Compose plugin
- Repo checked out on branch `claude/mcp-chrome-extension-BW3zj`
- `.env` populated (copy from `.env.example`)

## Topology
- `gateway`: FastAPI ingress (`/health`, `/hooks/*`, `/tools/invoke`, `/v1/*`)
- `worker`: background scheduler loop
- shared persistent volume: `/app/state` (`STATE_DIR`)

Compose file:
- `deploy/docker-compose.openclaw-local.yml`

## Start
```bash
docker compose -f deploy/docker-compose.openclaw-local.yml up --build -d gateway
```

To include worker:
```bash
docker compose -f deploy/docker-compose.openclaw-local.yml --profile worker up --build -d
```

## Validate
1. Health:
```bash
curl -sS http://localhost:8000/health
```
2. Pre-fund local gate:
```bash
bash scripts/prefund_gate.sh
```
3. State durability drill:
```bash
bash scripts/state_drill.sh
```

## Backup / Restore
Backup:
```bash
bash scripts/state_backup.sh ./local-state-backup.tar.gz
```

Restore:
```bash
bash scripts/state_restore.sh ./local-state-backup.tar.gz
```

## Stop
```bash
docker compose -f deploy/docker-compose.openclaw-local.yml down
```

## Notes
- `gateway` runs with `ENABLE_BACKGROUND_SCHEDULER=false`.
- `worker` runs with `ENABLE_BACKGROUND_SCHEDULER=true`.
- Both services share `STATE_DIR` for approvals, ledgers, SQLite, and pairing files.
