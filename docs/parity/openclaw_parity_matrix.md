# OpenClaw Parity Matrix

Status keys:
- `missing`
- `partial`
- `parity`
- `variance-approved`

| Capability | OpenClaw Reference | Arcuate Status | Notes |
|---|---|---|---|
| BlueBubbles channel ingress | `docs/channels/bluebubbles.md` | partial | Webhook scaffold added; full pairing/group policy pending |
| iMessage legacy channel | `docs/channels/imessage.md` | missing | Deferred; BlueBubbles is primary |
| Hooks wake endpoint | `docs/automation/webhook.md` | missing | To implement |
| Hooks agent endpoint | `docs/automation/webhook.md` | missing | To implement |
| Tools invoke HTTP | `docs/gateway/tools-invoke-http-api.md` | missing | To implement deny-list parity |
| Gateway method list parity | `src/gateway/server-methods-list.ts` | missing | P0 list to be implemented |
| Exec approvals API | `docs/tools/exec-approvals.md` | partial | Temporary runtime toggles exist; full store/model missing |
| Subagent spawn/announce/cascade | `docs/tools/subagents.md` | partial | Existing custom version; not full OpenClaw parity |
| SOUL bootstrap injection model | `docs/concepts/system-prompt.md` | missing | To port prompt assembly model |
| OpenAI compatible endpoints | `docs/gateway/openai-http-api.md` | missing | To implement `/v1/chat/completions` |
| OpenResponses endpoint | `docs/gateway/openresponses-http-api.md` | missing | To implement `/v1/responses` |
| Railway exit plan | N/A | parity | `docs/OPENCLAW_PLATFORM_MIGRATION_PLAN.md` |

