# OpenClaw Adoption Blueprint for Arcuate (Strict Parity Edition)

## 0) Execution Policy (Non-Negotiable)

We are not "inspired by" OpenClaw. We are **copying OpenClaw behavior by default**.

For every capability:
1. Define the business goal.
2. Document exactly how OpenClaw implements it (code/docs reference).
3. Implement the same behavior in Arcuate.
4. If behavior differs, add a written variance with a business/safety reason.

No variance is allowed without explicit justification in this document.

---

## 1) Critical Corrections (from previous draft)

1. iPhone/iMessage path: **BlueBubbles is primary** (not Twilio).
2. Legacy iMessage (`imsg`) is fallback only.
3. Twilio is optional for SMS/voice workflows, not the core iMessage path.
4. Rails and approvals must match OpenClaw semantics first, then Arcuate adds domain tooling.

OpenClaw references:
- `docs/channels/bluebubbles.md` (recommended iMessage integration, webhook auth expectations)
- `docs/channels/imessage.md` (legacy path)

---

## 2) Goal -> OpenClaw -> Arcuate Mapping Matrix

## 2.1 Founder can text agent from iPhone (primary win)
- Goal:
  - Founder sends/receives agent messages in iMessage.
- OpenClaw implementation:
  - BlueBubbles channel plugin, webhook ingress + REST send APIs.
  - Pairing/allowlist/group policy/mention gating handled at channel layer.
  - References: `docs/channels/bluebubbles.md`, `src/imessage/**`, `src/channels/**`.
- Arcuate implementation:
  - Build `channels.bluebubbles` adapter first.
  - Implement identical DM policy and group policy controls.
  - Keep legacy Twilio webhook only as optional secondary transport.
- Variance:
  - None planned for core behavior.
  - Optional Twilio kept for non-iMessage use cases (sales/outbound voice/SMS).

## 2.2 Webhook ingress rails (anti-abuse + deterministic routing)
- Goal:
  - Inbound webhook traffic cannot bypass auth/policy and cannot force unbounded sessions.
- OpenClaw implementation:
  - `/hooks/wake`, `/hooks/agent`, mapped `/hooks/<name>`.
  - Header token auth only, query token rejected.
  - Request auth rate limiting and request-size caps.
  - `allowRequestSessionKey=false` default.
  - References: `docs/automation/webhook.md`, `src/gateway/server-http.ts`.
- Arcuate implementation:
  - Mirror same route shape and defaults.
  - Separate hook token from gateway token.
  - Default fixed `hooks.defaultSessionKey="hook:ingress"` and no request override.
- Variance:
  - None.

## 2.3 Direct tool execution endpoint with hard deny list
- Goal:
  - Enable automation while preventing high-risk tool invocation over HTTP.
- OpenClaw implementation:
  - `POST /tools/invoke` with gateway auth + policy filtering.
  - Default HTTP deny list for high-risk tools (`sessions_spawn`, `sessions_send`, `gateway`, `whatsapp_login`).
  - 404 on policy-denied/unavailable tools.
  - References: `docs/gateway/tools-invoke-http-api.md`, `src/gateway/tools-invoke-http.ts`.
- Arcuate implementation:
  - Copy endpoint contract and deny-list behavior.
  - Keep deny list default-closed; require explicit override.
- Variance:
  - Add Arcuate-specific dangerous tools to deny list once introduced.
  - Reason: Arcuate will add CRM/billing/email mutation tools not present upstream.

## 2.4 Exec approvals (code execution rails)
- Goal:
  - Agent can execute code only under policy + approval + allowlist controls.
- OpenClaw implementation:
  - Host-local `exec-approvals.json` policy, per-agent allowlists.
  - `security: deny | allowlist | full`, ask modes, fallback behavior.
  - Safe-bin profiles and explicit protections against wrapper/shell bypasses.
  - References: `docs/tools/exec-approvals.md`, `src/gateway/server-methods-list.ts` (`exec.approval.*`, `exec.approvals.*`).
- Arcuate implementation:
  - Port this model directly (no ad-hoc boolean flags as final architecture).
  - Keep strict defaults: `deny` + ask-fallback deny.
  - Add approval UI/event transport in control channel.
- Variance:
  - Temporary (current): local runtime toggles for kill-switch bootstrapping.
  - Reason: immediate spend protection while full OpenClaw-style approvals are implemented.

## 2.5 System prompt + SOUL.md identity model
- Goal:
  - Agent identity is persistent, explicit, and controlled (not hidden in code prompts).
- OpenClaw implementation:
  - System prompt assembled by runtime from fixed sections + workspace bootstrap files.
  - Includes `SOUL.md`, `AGENTS.md`, `TOOLS.md`, `IDENTITY.md`, `USER.md`, etc.
  - Subagents use reduced prompt mode and smaller bootstrap set.
  - References: `docs/concepts/system-prompt.md`, `src/agents/system-prompt.ts`, `src/agents/workspace.ts`, `docs/reference/templates/SOUL.md`.
- Arcuate implementation:
  - Move agent identity into workspace bootstrap files.
  - Keep `SOUL.md` as first-class persona/boundary source.
  - Implement prompt-mode differences for subagents.
- Variance:
  - None.

## 2.6 Subagent swarm behavior (boss + workers)
- Goal:
  - Boss agent spawns worker agents, workers complete tasks, results route back safely.
- OpenClaw implementation:
  - `sessions_spawn` creates isolated subagent sessions.
  - Depth and fan-out limits (`maxSpawnDepth`, `maxChildrenPerAgent`, `maxConcurrent`).
  - Announce chain and cascade kill behavior.
  - References: `docs/tools/subagents.md`, `src/gateway/server-methods-list.ts` (sessions methods), `src/agents/**` session/subagent flow.
- Arcuate implementation:
  - Keep same lifecycle: spawn -> isolated run -> announce -> archive.
  - Set conservative defaults initially: depth=2, children=3, concurrent=4.
- Variance:
  - Lower concurrency defaults than OpenClaw examples.
  - Reason: cost containment while proving workflow quality.

## 2.7 Channel policy and anti-loop protections
- Goal:
  - Prevent bot loops and unauthorized command execution in channels.
- OpenClaw implementation:
  - DM policy + allowlists + pairing model.
  - Group policy (`allowlist|open|disabled`) and mention gating.
  - Per-channel controls and role/sender ID normalization.
  - References: `docs/channels/bluebubbles.md`, `docs/channels/pairing.md`, `docs/channels/group-messages.md`, `docs/channels/channel-routing.md`.
- Arcuate implementation:
  - Copy policy model exactly for iMessage and Slack.
  - Commands require explicit authorization; mention gating on group contexts.
- Variance:
  - None.

## 2.8 Gateway control plane parity
- Goal:
  - Arcuate has OpenClaw-equivalent runtime control surfaces.
- OpenClaw implementation:
  - WebSocket RPC method families for health/config/agent/sessions/exec approvals/nodes/cron.
  - References: `src/gateway/server-methods-list.ts`, `src/gateway/server-methods.ts`, `docs/gateway/protocol.md`.
- Arcuate implementation:
  - Implement method parity in priority buckets (P0-P2 below).
- Variance:
  - P2 methods may be deferred; document every defer.

---

## 3) Mandatory Method/Endpoint Parity Scope

## 3.1 P0 (must exist before enabling paid LLM usage)
1. `health`, `status`, `usage.status`, `usage.cost`
2. `config.get`, `config.set`, `config.apply`, `config.patch`
3. `agent`, `agent.wait`, `chat.send`, `chat.abort`, `chat.history`
4. `sessions.list`, `sessions.preview`, `sessions.patch`, `sessions.reset`, `sessions.delete`, `sessions.compact`
5. `exec.approval.request`, `exec.approval.waitDecision`, `exec.approval.resolve`
6. `exec.approvals.get`, `exec.approvals.set`
7. HTTP: `/hooks/wake`, `/hooks/agent`, `/tools/invoke`
8. Channel ingress: BlueBubbles webhook endpoint with strict auth

Reference:
- `src/gateway/server-methods-list.ts`
- `src/gateway/server-http.ts`

## 3.2 P1 (before production cutover)
1. OpenAI-compatible HTTP endpoints: `/v1/chat/completions`, `/v1/responses`
2. `update.run`, `models.list`, `agents.list`, `agents.create/update/delete`
3. cron jobs + webhook notifications
4. node/device pairing flows (if using remote nodes)

## 3.3 P2 (after cutover)
1. Extended channel/plugin ecosystem
2. canvas/a2ui hosting parity
3. non-critical method families

---

## 4) Implementation Sequence (Strict, Gate-Based)

## Phase A: Parity Harness + Freeze
- Deliverables:
  1. Create `docs/parity/openclaw_parity_matrix.md` with every method/endpoint/tool.
  2. Mark each item: `missing | partial | parity | variance-approved`.
  3. Freeze new feature work not in parity scope.
- Exit gate:
  - Parity matrix complete and reviewed.

## Phase B: Channel First-Win (iMessage via BlueBubbles)
- Deliverables:
  1. BlueBubbles adapter with webhook auth + DM/group policy + pairing.
  2. Founders can send `/status` equivalent and get deterministic reply.
  3. Basic reply loop (inbound iMessage -> agent -> outbound iMessage).
- Exit gate:
  - iPhone loop works end-to-end in staging with no Discord dependency.

## Phase C: Rails Core (before Anthropic re-fund)
- Deliverables:
  1. Exec approvals model (OpenClaw-style) wired and enforced.
  2. `/tools/invoke` deny-list parity.
  3. Budget caps (daily/session/run) + run abort + global panic.
- Exit gate:
  - Forced loop simulation cannot exceed configured budget and auto-aborts.

## Phase D: SOUL + Prompt + Subagent Runtime
- Deliverables:
  1. Workspace bootstrap injection parity (`SOUL.md`, `AGENTS.md`, etc.).
  2. Subagent prompt-mode parity.
  3. `sessions_spawn` + announce chain + cascade kill.
- Exit gate:
  - Boss->worker workflow completes and worker auto-shutdown is verified.

## Phase E: Arcuate Domain Tools (after parity)
- Deliverables:
  1. `arcuate_gmail`, `arcuate_drive`, `arcuate_docs`, `arcuate_corpus_builder` tools.
  2. “Michelle docs -> corpus doc” flow as scripted task.
- Exit gate:
  - Deterministic corpus generation test passes from iMessage trigger.

---

## 5) Variance Register (Required for any differences)

Use this template for every divergence from OpenClaw behavior:

- Capability:
- OpenClaw behavior (source):
- Arcuate behavior:
- Why variance is required:
- Risk introduced:
- Compensating control:
- Owner:
- Review date:

Current approved variances:
1. Temporary local kill-switch toggles exist before full exec-approvals parity.
2. Initial subagent concurrency lower than OpenClaw examples to reduce spend risk.

---

## 6) Safety Rules Before Re-Enabling Paid Models

Do not re-fund Anthropic until all are true:
1. BlueBubbles ingress works in staging with auth enabled.
2. P0 parity endpoints/methods implemented.
3. Exec approvals enforced with deny-by-default.
4. Budget circuit breaker tested (hard stop confirmed).
5. Panic switch tested (active runs aborted, outbound blocked).
6. Loop simulation test passes (no runaway recursion).

---

## 7) Concrete Next 10 Tasks (exact order)

1. Implement BlueBubbles channel adapter skeleton (`channels.bluebubbles`) and webhook auth.
2. Add pairing + allowlist + group policy controls matching OpenClaw docs.
3. Replace Twilio-first founder path with BlueBubbles-first route in runtime config.
4. Implement `/hooks/wake` and `/hooks/agent` with OpenClaw auth/session-key constraints.
5. Implement `/tools/invoke` with default deny list parity.
6. Build persistent exec approvals store (`exec-approvals.json` equivalent).
7. Wire `exec.approval.*` request/wait/resolve method flow.
8. Add usage/cost accounting (`usage.status`, `usage.cost`) and hard budget stops.
9. Port workspace bootstrap injection (`SOUL.md`, `AGENTS.md`, `TOOLS.md`, etc.).
10. Implement `sessions_spawn` + announce + cascade kill for boss/worker flow.

---

## 8) OpenClaw Source Reference Index (used by this plan)

Channels / iMessage:
- `docs/channels/bluebubbles.md`
- `docs/channels/imessage.md`
- `docs/channels/pairing.md`
- `docs/channels/group-messages.md`
- `docs/channels/channel-routing.md`

Gateway / control plane:
- `src/gateway/server-methods-list.ts`
- `src/gateway/server-methods.ts`
- `src/gateway/server-http.ts`
- `docs/gateway/protocol.md`
- `docs/gateway/network-model.md`

HTTP APIs:
- `docs/automation/webhook.md`
- `docs/gateway/tools-invoke-http-api.md`
- `docs/gateway/openai-http-api.md`
- `docs/gateway/openresponses-http-api.md`

Exec rails:
- `docs/tools/exec-approvals.md`
- `docs/gateway/security/index.md`

Prompt / identity / SOUL:
- `docs/concepts/system-prompt.md`
- `docs/reference/templates/SOUL.md`
- `src/agents/system-prompt.ts`
- `src/agents/workspace.ts`

Subagents:
- `docs/tools/subagents.md`

Creator principles context (why this matters):
- `https://lexfridman.com/peter-steinberger`
- `https://lexfridman.com/peter-steinberger-transcript`
  - Interpreted planning principles used here: “AI that does things”, practical integrations, and strong operator control rails.

