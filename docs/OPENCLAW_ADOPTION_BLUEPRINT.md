# OpenClaw Adoption Blueprint for Arcuate

## Objective
Replatform `arcuate_agents` so the runtime is effectively **OpenClaw-compatible by default** (control plane, safety rails, plugin model, subagents, session tooling), then layer Arcuate-specific workflows on top.

This plan assumes:
- We prioritize **feature parity** with OpenClaw over preserving current Python architecture.
- We keep Arcuate domain logic (Gmail/Drive corpus workflows, healthcare-specific processes) as custom tools/plugins/workflows.
- We treat safety, cost caps, and kill switches as first-class requirements.

---

## 1) Recommended Strategy

## 1.1 Replatform, don’t retrofit
Your current Python codebase is small and single-agent. OpenClaw is a large, opinionated TypeScript platform with:
- WS gateway control plane
- HTTP API/webhook ingress
- plugin-based channels/tools
- embedded coding-agent runtime
- approvals + sandbox + policy stack
- subagent orchestration

Trying to “port features” into the current code incrementally will be slower and less reliable than adopting OpenClaw architecture directly.

**Recommendation:**
1. Create a new runtime layer in-repo (`platform/openclaw_core`) using OpenClaw patterns.
2. Move Arcuate logic into extensions/plugins/workflows.
3. Keep current Python service only as a temporary adapter during migration.

---

## 2) OpenClaw Surfaces to Copy (Rails + Interfaces)

## 2.1 Server surfaces
OpenClaw runs one gateway that multiplexes WS + HTTP.

### WebSocket control plane
- Single WS endpoint (upgrade on gateway host/port).
- Uses request/response/event frames.
- First frame is `connect` with role/scopes/device identity.

### HTTP endpoints (core)
- `POST /hooks/wake`
- `POST /hooks/agent`
- `POST /hooks/<mapped-name>` (mapping transform pipeline)
- `POST /tools/invoke`
- `POST /v1/chat/completions` (optional; OpenAI-compatible)
- `POST /v1/responses` (optional; OpenResponses-compatible)
- Canvas host routes:
  - `/__openclaw__/canvas/`
  - `/__openclaw__/a2ui/`
- Control UI routes (base path configurable)
- Channel/plugin HTTP routes under `/api/channels/*` (gateway-auth protected)

## 2.2 RPC method surface (WS)
OpenClaw exposes broad methods. Minimum parity buckets to copy:
- Health/status: `health`, `status`, usage methods
- Config/control-plane: `config.get/set/apply/patch`, `update.run`
- Agent/chat: `agent`, `agent.wait`, `chat.send`, `chat.abort`, `chat.history`
- Sessions: `sessions.list/preview/patch/reset/delete/compact`
- Subagent support via tools + session APIs
- Approvals: `exec.approval.request/waitDecision/resolve`, `exec.approvals.*`
- Node/device: pairing, invoke, events
- Models/skills: `models.list`, `skills.*`, `agents.*`

Source of truth in OpenClaw: `src/gateway/server-methods-list.ts` and `src/gateway/server-methods.ts`.

## 2.3 Webhook system
Copy these webhook characteristics:
- Token-authenticated (`Authorization: Bearer` or `x-openclaw-token`)
- Query token rejection (prevents accidental leakage)
- Request size limits, timeout handling
- Mapping/transforms pipeline (`/hooks/<name>`)
- Isolated async runs with returned `runId`
- Optional fixed/guarded session keys (`allowRequestSessionKey=false` by default)

---

## 3) Safety and Cost Rails to Copy First

## 3.1 Mandatory hard controls
1. Global panic switch:
- disable outbound messaging
- disable `exec`
- disable subagent spawn
- abort all active runs

2. Budget circuit breakers:
- hard daily/weekly spend cap per provider/model
- per-run token cap
- per-session token cap
- max tool-calls/run

3. Execution controls:
- allowlist-based exec approvals
- safe bins profile system (no interpreter bins without explicit hardened profiles)
- sandbox-by-default for non-main sessions

4. Sender/channel controls:
- DM pairing or allowlist by default
- group policy (`allowlist/open/disabled`) + mention gating

5. Control-plane auth:
- token/password auth for WS/HTTP
- brute-force rate limiting
- strict trusted proxy handling

## 3.2 Runtime kill commands
Implement operator commands equivalent to:
- `/stop` (per-session abort + child subagent cascade)
- global `panic on/off`
- `subagents kill all`

---

## 4) Integration Architecture to Copy (Plug-and-Play)

## 4.1 Plugin model
Adopt extension packages for:
- channels (iMessage/BlueBubbles, Slack, Discord, Telegram, etc.)
- tool bundles (Gmail/Drive/Docs/Zoom/CRM)
- hook packs

## 4.2 Channel adapter contract
Each channel plugin should implement:
- config schema
- sender identity normalization
- DM/group policy handling
- outbound send/reply/media support
- optional reactions/actions
- runtime health/probe
- onboarding helper

## 4.3 Tool architecture
- Core coding tools (`read/write/edit/apply_patch/exec/process`) with policy wrapper.
- OpenClaw-like tools (`sessions_*`, `subagents`, `message`, `gateway`, `web_*`).
- Arcuate domain tools as separate plugins:
  - `arcuate_gmail`
  - `arcuate_drive`
  - `arcuate_docs`
  - `arcuate_corpus_builder`
  - `arcuate_client_ops`

---

## 5) Arcuate Swarm Model (Target)

## 5.1 Agent classes
1. `boss` agent:
- receives founder requests
- decomposes into plans
- spawns workers
- synthesizes and returns final output

2. `worker` agents (ephemeral):
- task-scoped capabilities
- strict timeout and budget
- auto-cleanup/archive

3. `specialist` agents (optional):
- corpus specialist
- outbound specialist
- analytics specialist

## 5.2 Spawn policy
- `maxSpawnDepth`: 2 initially
- `maxChildrenPerAgent`: 3 initially
- separate queue lanes for `main`, `subagent`, `cron`

## 5.3 Announce model
- workers announce completion to parent session
- parent decides what reaches founder
- no direct worker-to-user sends without explicit policy

---

## 6) Migration Plan (Execution)

## Phase 0: Foundation and governance (Week 1)
Deliverables:
- Create `platform/openclaw_core` service skeleton (TS monorepo or package).
- Define parity matrix: OpenClaw feature -> Arcuate implementation status.
- Add security policy baseline and SLOs.

Acceptance criteria:
- architecture decision record approved
- parity tracker checked into repo

## Phase 1: Rails-first gateway (Weeks 2-3)
Deliverables:
- WS gateway + auth + scope model
- HTTP routes:
  - `/hooks/*`
  - `/tools/invoke`
  - `/v1/chat/completions` (optional on)
  - `/v1/responses` (optional on)
- kill switch + abort APIs
- spend/token budget manager

Acceptance criteria:
- panic switch tested end-to-end
- budget cap reliably halts runs
- webhook auth/rate-limit tests passing

## Phase 2: Core agent runtime parity (Weeks 4-6)
Deliverables:
- System prompt assembly model (with AGENTS/SOUL/TOOLS/MEMORY bootstraps)
- Tool policy pipeline (global + per-agent + per-group + subagent-depth)
- exec approvals and safe bins
- session store + compaction + `/stop`

Acceptance criteria:
- can run coding loop with controlled tool execution
- policy denials enforce hard boundaries

## Phase 3: Subagents and orchestration (Weeks 7-8)
Deliverables:
- `sessions_spawn`, `subagents`, `sessions_send/history/list`
- parent-child lifecycle registry
- cascade kill + announce + auto-archive

Acceptance criteria:
- boss->worker->boss loop works with timeout and cleanup
- nested depth limits enforced

## Phase 4: Channel migration (Weeks 9-10)
Deliverables:
- BlueBubbles (recommended iMessage path) as primary founder interface
- Slack channel plugin (secondary)
- Discord optional/deprioritized

Acceptance criteria:
- founders operate through iMessage with pairing/allowlist and group safety

## Phase 5: Arcuate domain layer (Weeks 11-13)
Deliverables:
- corpus workflow tools
- client onboarding packet generator workflow
- Gmail/Drive/Docs ingestion + transformation pipelines as tools/hooks

Acceptance criteria:
- “Michelle corpus” workflow runs via spawned worker and produces deterministic outputs

## Phase 6: Cutover and decommission (Weeks 14-15)
Deliverables:
- canary rollout
- incident runbooks
- deprecate old Python direct-exec paths

Acceptance criteria:
- production traffic on new gateway
- old stack read-only/decommissioned

---

## 7) Concrete Backlog (First 30 days)

## Sprint A
- Implement gateway auth and connect protocol.
- Implement `/hooks/wake`, `/hooks/agent` with token and payload limits.
- Implement panic switch + run abort registry.
- Add cost ledger schema and provider budget checks.

## Sprint B
- Add tool policy layer and deny-by-default dangerous tools.
- Implement `exec` wrapper with approval request/resolve flow.
- Add `/tools/invoke` with HTTP deny list.
- Add session store + `chat.send`, `chat.abort`, `chat.history`.

## Sprint C
- Add `sessions_*` tools and `sessions_spawn`.
- Add subagent registry, announce flow, cascade kill.
- Integrate BlueBubbles plugin.

---

## 8) Repo Structure Proposal

```text
arcuate_agents/
  docs/
    OPENCLAW_ADOPTION_BLUEPRINT.md
    parity/
      openclaw_parity_matrix.md
  platform/
    openclaw_core/
      gateway/
      agents/
      channels/
      tools/
      hooks/
      security/
  integrations/
    arcuate_gmail/
    arcuate_drive/
    arcuate_docs/
    arcuate_zoom/
  workflows/
    corpus_builder/
    onboarding_packet/
  legacy_python/
    (current src/chief_of_staff during migration window)
```

---

## 9) Build-vs-Copy Decision

## Preferred
- **Fork OpenClaw** as upstream base and maintain an `arcuate` branch.
- Add Arcuate plugins/workflows in-tree.
- Periodically merge upstream OpenClaw.

## Fallback
- Re-implement from scratch using OpenClaw design references.
- Higher risk, slower parity, more maintenance debt.

---

## 10) Non-Negotiable Policies for Production

1. `exec` requires approval unless explicit allowlist hit and policy permits.
2. Default DM policy is `pairing` or strict allowlist.
3. Group replies require mention unless explicitly exempted.
4. `sessions_spawn` capped by depth/concurrency/children.
5. Provider spend cap enforced before model call.
6. Global panic switch available to founders/operators.
7. Full audit trail for tool calls, approvals, outbound actions.

---

## 11) Immediate Next Steps

1. Approve replatform decision (`fork/adopt OpenClaw core` vs `rebuild`).
2. Open 4 epic tickets:
- `EPIC-1 Gateway + Rails`
- `EPIC-2 Agent Runtime + Tool Policy`
- `EPIC-3 Subagents + Swarm`
- `EPIC-4 iMessage + Arcuate Workflows`
3. Create parity matrix from OpenClaw method/endpoint/tool surfaces.
4. Implement panic switch + budget caps before enabling autonomous execution.

---

## Reference inventory used for this plan
- OpenClaw gateway HTTP routing: `src/gateway/server-http.ts`
- OpenClaw RPC method index: `src/gateway/server-methods-list.ts`
- Gateway method dispatcher: `src/gateway/server-methods.ts`
- Webhooks docs: `docs/automation/webhook.md`
- OpenAI-compatible API docs: `docs/gateway/openai-http-api.md`
- OpenResponses API docs: `docs/gateway/openresponses-http-api.md`
- Tools invoke docs: `docs/gateway/tools-invoke-http-api.md`
- Protocol docs: `docs/gateway/protocol.md`
- Network model docs: `docs/gateway/network-model.md`
- Channel index docs: `docs/channels/index.md`
- Exec approvals and security docs: `docs/tools/exec-approvals.md`, `docs/gateway/security/index.md`
