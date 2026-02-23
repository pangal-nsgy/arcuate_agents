# DB + Runtime Rethink (Mirror OpenClaw, Fit Arcuate)

## Decision
- Do not keep a Railway-first architecture for the core gateway runtime.
- Mirror OpenClaw's model: one long-lived gateway on a persistent host, with host-local state as the source of truth for runtime control paths.
- Keep Railway optional for non-critical workloads during transition.

OpenClaw reference: `https://github.com/openclaw/openclaw`

## Why
- Arcuate's critical paths (BlueBubbles ingress, approvals, budget rails, voice command gating) are stateful and safety-sensitive.
- Railway's stateless/process-churn model increases risk for local runtime state and operator control loops.
- OpenClaw intentionally centers state under a host-local state dir and keeps gateway ownership on one host.

## What OpenClaw Is Doing
- Single gateway daemon with WS control plane and HTTP ingress.
- Mutable state under `~/.openclaw` (or configured state dir).
- Mixed storage:
  - JSON/JSONL files for approvals/pairing/queues/transcripts/logs.
  - SQLite where relational or indexed local lookup is needed.
  - No managed cloud DB required for core control-plane correctness.

## Arcuate Target Storage Model
Use `STATE_DIR` (default `~/.arcuate_agents`) as runtime truth.

1. Control-plane state (authoritative, low-latency)
- `exec-approvals.json`
- `usage-ledger.json`
- `bluebubbles-pairing.json`
- hook transform files
- Future: outbound queue files, run journals (`jsonl`)

2. Relational local state (SQLite with WAL)
- `chief_of_staff.db`
- keep for: conversations, idempotency keys, scheduled actions, sub-agent runs, activity feed

3. Vector state
- `chroma_data/` in `STATE_DIR`

4. Cloud DB (later, optional)
- Add Postgres only for analytics/reporting or cross-host reads.
- Do not put approvals/pairing/budget gates behind network DB in phase 1.

## Migration Plan
## Phase 0 (done in this branch)
- Introduced `STATE_DIR` configuration in `src/chief_of_staff/config.py`.
- Runtime path defaults now resolve under `STATE_DIR`.

## Phase 1
- Enable SQLite WAL + busy timeout at connection open.
- Add `schema_migrations` table and explicit migration files.
- Add backup/restore scripts for `STATE_DIR`.

## Phase 2
- Split DB concerns:
  - `runtime.db` (hot-path control data, idempotency, runs)
  - `knowledge.db` (documents/search metadata)
- Keep both local to gateway host.

## Phase 3
- Introduce optional async replication:
  - periodic export of selected tables/events to Postgres/object storage.
- Preserve local-first execution semantics.

## Hard Rules
- Approvals, pairing, and budget-stop checks must succeed fully offline (host-local only).
- Every inbound webhook path must remain idempotent with local durable writes.
- Network DB outages must not disable safety rails.

## Exit Criteria (before scaling infra spend)
1. BlueBubbles + hooks + approvals pass end-to-end on non-Railway host.
2. Budget stop works with process restart simulation.
3. Restore test from `STATE_DIR` backup succeeds.
4. No critical path requires managed cloud DB availability.
