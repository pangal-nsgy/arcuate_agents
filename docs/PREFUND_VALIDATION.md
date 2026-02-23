# Pre-Fund Validation Gate (Anthropic)

Use this before re-funding Anthropic API credits.

## Reference
- Arcuate branch: `https://github.com/pangal-nsgy/arcuate_agents/tree/claude/mcp-chrome-extension-BW3zj`
- OpenClaw parity source: `https://github.com/openclaw/openclaw`

## Goal
Confirm rails/parity in a sandbox or staging environment before paid-model spend.

## Mandatory Pass Criteria
1. Hooks auth and routing:
- `/hooks/wake`, `/hooks/agent`, `/hooks/{name}` reject unauthorized requests.
- Valid token path succeeds.
2. Exec approvals:
- `exec.approvals.*` and `exec.approval.*` actions work.
- Deny-by-default policy verified.
3. Budget circuit breakers:
- `usage.status` and `usage.cost` reachable.
- run/session/day budget stop enforced in:
  - `/tools/invoke`
  - hooks execution paths
  - control command `cmd:`
4. BlueBubbles safety:
- pairing policy works (`/pair list|approve|deny|paired|unpair`).
- group policy and mention gating enforced.
5. OpenAI compatibility:
- `/v1/chat/completions`
- `/v1/responses`
6. Voice command safety:
- transcript command returns approval id and deterministic pending/approved/denied confirmation.
7. State durability drill:
- backup/restore succeeds for `STATE_DIR`.
- restored SQLite + approvals + ledgers + pairing files are readable and consistent.

## Runbook
1. Set sandbox/staging env vars:
- `GATEWAY_AUTH_TOKEN`
- `HOOKS_TOKEN`
- `BLUEBUBBLES_WEBHOOK_SECRET` (if BlueBubbles path under test)
- conservative budgets:
  - `USAGE_RUN_BUDGET_USD`
  - `USAGE_SESSION_BUDGET_USD`
  - `USAGE_DAY_BUDGET_USD`
2. Run state durability drill:
```bash
bash scripts/state_drill.sh
```
3. Run local parity test suite:
```bash
PYTHONPATH=src pytest -q tests/test_gateway_hooks_and_tools.py tests/test_bluebubbles_webhook.py tests/test_control_commands.py tests/test_voice_commands.py
```
4. Run pre-fund script:
```bash
bash scripts/prefund_gate.sh
```
5. If validating deployed staging:
```bash
BASE_URL="https://<staging-host>" GATEWAY_AUTH_TOKEN="<token>" HOOKS_TOKEN="<token>" bash scripts/prefund_gate.sh
```
6. Optional: skip drill inside prefund gate if you already ran it:
```bash
PREFUND_SKIP_STATE_DRILL=1 bash scripts/prefund_gate.sh
```

## Funding Decision
Fund Anthropic only when all mandatory pass criteria above are green in sandbox/staging and at least one real end-to-end founder flow is verified (iMessage ingress -> approval/budget rails -> deterministic response).
