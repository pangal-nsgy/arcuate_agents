# OpenClaw Infrastructure Migration Plan (Railway Exit + Voice Execution)

## Objective
Stand up an OpenClaw-style runtime for Arcuate with:
1. BlueBubbles-first iMessage control plane.
2. Strong rails/approvals/cost circuit breakers.
3. Boss + worker swarm execution.
4. Voice command execution path for live meetings.
5. Clear migration path off Railway.

---

## 1) Hosting Strategy: Railway -> OpenClaw-style Runtime

## Phase 1 (parallel run)
- Keep Railway serving current Python app.
- Stand up new gateway runtime on dedicated host (Fly.io/Render/K8s/VM).
- Route only BlueBubbles + hooks traffic to new runtime first.

## Phase 2 (control-plane cutover)
- Move `/hooks/*`, `/tools/invoke`, channel webhooks to new runtime.
- Keep ingestion workers temporarily on Railway if needed.

## Phase 3 (full cutover)
- Move all agent runtime + orchestration off Railway.
- Decommission Railway app or keep read-only fallback endpoint.

## Recommended target topology
- `gateway` service: WS + HTTP mux, auth, sessions, approvals.
- `worker` service: tool execution lane + subagent runs.
- `state_dir` (host-local): approvals, pairing, ledgers, queues, transforms, transcripts.
- `sqlite` (host-local): runtime + knowledge relational state.
- `blob/analytics` (optional later): replicas/exports only, not safety-critical source of truth.
- `obs` stack: OpenTelemetry + logs + alerts.

---

## 2) OpenClaw Parity Requirements (Must-Have)

1. Hooks parity:
- `POST /hooks/wake`
- `POST /hooks/agent`
- mapped `POST /hooks/<name>`
- token auth in header only, query token blocked.

2. Tools parity:
- `POST /tools/invoke` with default deny list for high-risk tools.

3. Session/subagent parity:
- isolated child session spawn
- announce chain to parent
- cascade kill and depth limits.

4. Exec approvals parity:
- host-local approval policy store
- allowlist mode + ask mode + fallback deny
- safe-bin profiles.

5. iMessage parity:
- BlueBubbles webhook ingress + REST send
- pairing, allowlist, group policy, mention gating.

---

## 3) Voice Agent Execution Plan (Zoom/Meet/Teams)

## Goal
During live meetings, spoken commands can trigger safe execution and produce spoken confirmation.

## OpenClaw-aligned approach
- Inbound voice transcripts are untrusted webhook events.
- They map to hook actions (`agent` runs) through controlled hook mappings.
- Execution still goes through normal approvals/policy pipeline.

## Arcuate implementation
1. Capture live transcripts:
- Primary: Recall.ai real-time transcript webhook (`/webhooks/recall/transcript`).
- Secondary: Zoom recording transcript ingestion for post-call tasks.

2. Voice command trigger policy:
- Require explicit prefix phrase for actionable commands (ex: "agent execute").
- Gate by meeting allowlist + authorized speaker identity.
- Route to isolated session key: `hook:voice:<meeting_id>`.

3. Execution controls:
- No direct raw exec from transcript.
- Transcript command -> tool request -> approval flow -> execution.
- Responses are summarized and sent back via meeting bot TTS.

4. Voice response path:
- Initial: text response back into meeting channel/transcript notes.
- Next: TTS response pipeline (ElevenLabs/voice provider) once policy rails are stable.

## Safety defaults
- `voice_exec_enabled=false` by default.
- `voice_command_allowlist` required.
- If speaker identity confidence is low -> no exec, only suggestion output.

---

## 4) Immediate Work Packages

## WP-1 (now)
- BlueBubbles webhook ingress + outbound send path.
- Guardian workflow stabilization.
- Parity matrix tracking doc.

## WP-2
- `/hooks/*` and `/tools/invoke` parity endpoints.
- Gateway auth + rate limit + deny list.

## WP-3
- Exec approval service + UI path.
- Budget circuit breakers + panic switch.

## WP-4
- Subagent session runtime (spawn/announce/kill).

## WP-5
- Voice command pipeline from Recall.ai transcripts into approval-gated tasks.

---

## 5) Cutover Readiness Checklist

Before Anthropic re-fund and production enablement:
1. BlueBubbles iPhone loop passes in staging.
2. Exec approvals deny-by-default verified.
3. Budget cap auto-stop verified.
4. Panic switch tested on active runs.
5. Voice command path tested in "dry-run" mode (no exec).
6. Guardian pipelines stable (validate + merge + deploy).

---

## 6) Known Inputs
- Twilio number: `+1 628-212-7401` (secondary channel, not primary iMessage path).
