# Next Window Handoff (Resume Fast)

## Repo + Branch
- Repo: `https://github.com/pangal-nsgy/arcuate_agents`
- Active branch: `claude/mcp-chrome-extension-BW3zj`
- Latest implementation commit: `7ca6fc1`

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

## Current Safety Defaults
- LLM inbound: off by default unless explicitly resumed.
- Command execution: off by default unless explicitly resumed.
- Voice command execution: off by default (`VOICE_EXEC_ENABLED=false`, `VOICE_EXEC_DRY_RUN=true`).

## Immediate Next Steps (Do In This Exact Order)
1. Implement full OpenClaw-style exec approvals model:
   - host-local persistent approvals store (equivalent to `exec-approvals.json`)
   - API surface parity for:
     - `exec.approvals.get`
     - `exec.approvals.set`
     - `exec.approval.request`
     - `exec.approval.waitDecision`
     - `exec.approval.resolve`
2. Replace temporary runtime rails toggles with approvals-enforced execution flow.
3. Implement mapped hooks parity (`POST /hooks/<name>` transform/mapping behavior).
4. Extend BlueBubbles parity:
   - pairing model
   - group policy (`allowlist/open/disabled`)
   - mention gating
5. Implement usage/cost circuit breakers:
   - `usage.status`
   - `usage.cost`
   - enforced run/session/day budget stops.
6. Add OpenAI compatibility endpoints:
   - `/v1/chat/completions`
   - `/v1/responses`

## Twilio Note
- Secondary number provided by user: `+1 628-212-7401`
- Keep as secondary channel; iMessage primary remains BlueBubbles.

## Validation Commands
Run after each slice:
- `PYTHONPATH=src ruff check <changed_files>`
- `PYTHONPATH=src pytest -q tests/test_gateway_hooks_and_tools.py tests/test_bluebubbles_webhook.py tests/test_control_commands.py tests/test_voice_commands.py`

## Copy/Paste Prompt For New Window
Use this as the first message in the next session:

"Open `https://github.com/pangal-nsgy/arcuate_agents`, checkout branch `claude/mcp-chrome-extension-BW3zj`, read `docs/NEXT_WINDOW_HANDOFF.md`, `docs/IMPLEMENTATION_PROGRESS.md`, and `docs/OPENCLAW_ADOPTION_BLUEPRINT.md`, then continue implementation from Step 1 (full exec approvals parity). Commit and push progress as you go."

