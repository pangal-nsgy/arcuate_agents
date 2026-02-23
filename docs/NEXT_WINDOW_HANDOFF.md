# Next Window Handoff (Resume Fast)

## Repo + Branch
- Repo: `https://github.com/pangal-nsgy/arcuate_agents`
- Active branch: `claude/mcp-chrome-extension-BW3zj`
- OpenClaw reference repo: `https://github.com/openclaw/openclaw`
- Latest implementation commit: `branch HEAD` (currently `7a5fa14`)

## What Is Already Done
1. Strict OpenClaw parity blueprint:
   - `docs/OPENCLAW_ADOPTION_BLUEPRINT.md`
2. Infrastructure migration plan (including Railway exit + voice path):
   - `docs/OPENCLAW_PLATFORM_MIGRATION_PLAN.md`
3. Progress log:
   - `docs/IMPLEMENTATION_PROGRESS.md`
4. Parity tracker:
   - `docs/parity/openclaw_parity_matrix.md`
5. Guardian workflow fixes:
   - `.github/workflows/collab-guardian.yml`
6. BlueBubbles scaffold:
   - `src/chief_of_staff/webhooks/bluebubbles.py`
   - `src/chief_of_staff/communication/bluebubbles.py`
7. OpenClaw-style gateway surfaces:
   - `src/chief_of_staff/gateway/hooks.py` (`/hooks/wake`, `/hooks/agent`, `/hooks/runs/{run_id}`)
   - `src/chief_of_staff/gateway/tools_invoke.py` (`/tools/invoke`)
   - `src/chief_of_staff/gateway/auth.py`
8. Voice-command scaffold from meeting transcripts (safe-by-default):
   - `src/chief_of_staff/ingestion/voice_commands.py`
   - wired in `src/chief_of_staff/webhooks/recall.py`
9. Exec approvals parity + persistent store:
   - `src/chief_of_staff/gateway/exec_approvals.py`
   - `exec.approvals.get`, `exec.approvals.set`
   - `exec.approval.request`, `exec.approval.waitDecision`, `exec.approval.resolve`
10. Approvals-enforced command execution flow:
   - `src/chief_of_staff/communication/control_commands.py`
11. Mapped hook parity (`POST /hooks/{name}` with mapping/templates/transforms):
   - `src/chief_of_staff/gateway/hooks.py`
12. BlueBubbles parity extensions:
   - pairing store + approve/deny control commands
   - group policy (`allowlist/open/disabled`)
   - mention gating
   - `src/chief_of_staff/communication/bluebubbles_pairing.py`
   - `src/chief_of_staff/webhooks/bluebubbles.py`
13. Usage/cost circuit breakers:
   - `src/chief_of_staff/gateway/usage_budget.py`
   - `usage.status`, `usage.cost`
   - run/session/day budget stops enforced in execution paths
14. OpenAI compatibility endpoints:
   - `src/chief_of_staff/gateway/openai_compat.py`
   - `/v1/chat/completions`
   - `/v1/responses`

## Current Safety Defaults
- LLM inbound: off by default unless explicitly resumed.
- Command execution: off by default unless explicitly resumed.
- Voice command execution: off by default (`VOICE_EXEC_ENABLED=false`, `VOICE_EXEC_DRY_RUN=true`).

## Immediate Next Steps (Do In This Exact Order)
1. Add integration-level tests for concurrent approvals + budget stop enforcement across hooks/tools/control commands.
2. Harden BlueBubbles pairing/operator UX and validate founder-first routing behavior.
3. Complete remaining P0 control-plane parity gaps referenced in `docs/OPENCLAW_ADOPTION_BLUEPRINT.md`.
4. Wire voice transcript command execution to approval IDs and delivery confirmations.
5. Add non-Railway runtime deployment manifests + cutover runbook.

## Twilio Note
- Secondary number provided by user: `+1 628-212-7401`
- Keep as secondary channel; iMessage primary remains BlueBubbles.

## Validation Commands
Run after each slice:
- `PYTHONPATH=src ruff check <changed_files>`
- `PYTHONPATH=src pytest -q tests/test_gateway_hooks_and_tools.py tests/test_bluebubbles_webhook.py tests/test_control_commands.py tests/test_voice_commands.py`

## Copy/Paste Prompt For New Window
Use this as the first message in the next session:

"Open `https://github.com/pangal-nsgy/arcuate_agents` (branch `claude/mcp-chrome-extension-BW3zj`) and use `https://github.com/openclaw/openclaw` as parity reference. Read `docs/NEXT_WINDOW_HANDOFF.md`, `docs/IMPLEMENTATION_PROGRESS.md`, and `docs/OPENCLAW_ADOPTION_BLUEPRINT.md`, then continue from the Immediate Next Steps list. Commit and push progress as you go."
