# Arcuate Chief of Staff Agent

## What This Is
AI Chief of Staff for Arcuate Health — a healthcare startup doing agentic outreach for aesthetic practices (ElevenLabs + Twilio voice calls to practices).
The agent ingests all company knowledge and lets founders interact via Discord. Supports self-modification, code self-modification, persistent memory, sub-agent spawning, and a live activity dashboard.

## Architecture (as of 2026-02-15)

### Agent System
- **Config-driven agents** — each agent is defined in `agents/<name>.yaml` (system prompt, tools, permissions)
- **Self-modification** — agents can update standing instructions, rewrite their own system prompt, and change their Discord triage/listener behavior — all via tools
- **Code self-modification** — agents can read, edit, and deploy their own Python/YAML source code via GitHub REST API
- **Persistent memory** — per-agent memory files in `agent_memory/<name>.md`, survives restarts
- **Sub-agent spawning** — Chief of Staff can create specialized agents via `create_sub_agent` tool, then persist them via code ops
- **Task delegation** — delegates tasks to sub-agents via `delegate_task` tool
- **Activity tracking** — every action logged to SQLite `agent_activity` table (22 action types across all channels)
- **Dashboard** — live web dashboard at `/dashboard` showing all agent activity, auto-refreshes every 5s

### Key Directories
```
agents/                  # Agent YAML configs (self-modifiable)
  chief_of_staff.yaml    # Main agent config
agent_memory/            # Persistent memory per agent
  chief_of_staff.md      # Learnings, preferences, facts
src/chief_of_staff/
  agent/
    core.py              # Agent loop (async, config-driven, timeouts, activity-tracked)
    tools.py             # 17 tools including self-mod, memory, delegation, code ops (error-wrapped)
    retry.py             # Retry with exponential backoff for transient API failures
    activity.py          # Activity logging to SQLite (22 action types)
    code_ops.py          # Code self-modification via GitHub REST API
    memory.py            # Persistent memory read/write/search (async-safe)
    registry.py          # Agent config loading from YAML
    planner.py           # Multi-step task planner
  dashboard/
    routes.py            # Dashboard API + HTML frontend (single-page app)
  communication/         # Discord, SMS, email, error reporting
    discord_bot.py       # Discord interface (primary), triage + response
    error_reporter.py    # Posts errors to #bot-errors Discord channel
    sms.py               # Twilio WhatsApp/SMS
    email.py             # Gmail API send (authenticated as agent1@arcuatehealth.com)
    _google_auth.py      # Google OAuth helper (file + env var modes)
  ingestion/             # Gmail, GDocs, ElevenLabs, Zoom
    gmail.py             # Gmail API email ingestion
    gdocs.py             # Google Docs/Drive ingestion
    elevenlabs.py        # ElevenLabs transcript ingestion
    zoom.py              # Zoom cloud recording ingestion
    recall_bot.py        # Recall.ai meeting bot
    scheduler.py         # Background sync (every 5 min, crash-protected)
  knowledge/             # ChromaDB + SQLite
    store.py             # Unified knowledge interface (graceful degradation)
    vectordb.py          # ChromaDB semantic search
    database.py          # SQLite structured metadata
  webhooks/              # Twilio, Gmail push, Zoom, Recall.ai
tests/                   # Test suite (16 tests)
  conftest.py            # Shared fixtures (mock configs, mock Anthropic responses)
  test_core.py           # Agent loop: text response, timeout, iteration limit
  test_tools.py          # Tool dispatch: known tool, unknown tool, error wrapping
  test_retry.py          # Retry: 429 handling, max retries, backoff, non-retryable errors
  test_error_handling.py # Tool failures return strings, not exceptions
```

### Tools (17 total)
| Tool | Category | Description |
|------|----------|-------------|
| search_knowledge | Knowledge | Semantic search across all company data |
| list_recent_emails | Knowledge | List emails from DB |
| search_meetings | Knowledge | Search meeting transcripts |
| send_sms | Communication | WhatsApp/SMS via Twilio |
| send_email | Communication | Gmail API (sends from agent1@arcuatehealth.com) |
| draft_document | Communication | Create draft docs |
| send_meeting_bot | Meetings | Dispatch Recall.ai bot (NOT configured — code is built but Recall.ai credentials are blank) |
| update_own_instructions | Self-Mod | Add/remove/replace standing instructions |
| update_system_prompt | Self-Mod | Rewrite the base system prompt entirely |
| update_triage_config | Self-Mod | Change Discord listener behavior (triage prompt + trigger words) |
| remember | Memory | Store persistent learnings |
| recall_memory | Memory | Search persistent memory |
| create_sub_agent | Delegation | Create new agent from YAML config |
| delegate_task | Delegation | Send task to sub-agent, get result |
| read_own_code | Code Ops | Read any file in the repo via GitHub API |
| edit_own_code | Code Ops | Validate syntax + stage a file change |
| deploy_changes | Code Ops | Atomic commit of all staged changes, triggers Railway deploy |

### Activity Tracking (22 action types)
All channels are tracked in the `agent_activity` SQLite table:
- **Messages**: `message_received`, `message_sent` (Discord)
- **SMS/WhatsApp**: `sms_received`, `sms_sent` (Twilio webhooks + outbound)
- **Agent operations**: `tool_use`, `knowledge_search`, `web_search`, `config_update`, `memory_write`, `memory_read`
- **Delegation**: `sub_agent_spawn`, `delegation`
- **Ingestion**: `call_ingested` (ElevenLabs), `email_ingested` (Gmail), `doc_ingested` (GDocs), `meeting_ingested` (Zoom/Recall)
- **Code ops**: `code_read`, `code_edit`, `code_deploy`
- **System**: `ingestion_sync` (background scheduler), `webhook_received` (Gmail/Zoom/Recall push), `error`

### Code Self-Modification
The agent can read, edit, and deploy its own source code via the GitHub REST API:
- **`read_own_code`** — reads any file from the repo (GitHub Contents API)
- **`edit_own_code`** — syntax-validates (ast.parse for .py, yaml.safe_load for .yaml) and stages changes in memory
- **`deploy_changes`** — commits all staged edits as one atomic commit via Git Data API (blobs -> tree -> commit -> ref update), Railway auto-deploys
- **Safety**: blocked paths (.env, credentials.json, token.json, *.db, chroma_data/, .git/, venv/), syntax validation, permission-gated (`can_modify_code`), full audit trail
- **Requires**: `GITHUB_TOKEN` env var (fine-grained PAT with Contents read/write on arcuate_agents)
- **Module**: `src/chief_of_staff/agent/code_ops.py`
- **Sub-agent persistence**: agents created via `create_sub_agent` only live in memory. To persist across deploys, use `edit_own_code` to write the YAML to `agents/`, then `deploy_changes` to commit it.

Files with tracking wired in:
- `discord_bot.py` — message_received, message_sent, error
- `webhooks/twilio.py` — sms_received, sms_sent, error
- `communication/sms.py` — sms_sent
- `ingestion/elevenlabs.py` — call_ingested
- `ingestion/scheduler.py` — email_ingested, doc_ingested, ingestion_sync, error
- `webhooks/gmail.py` — webhook_received, email_ingested
- `webhooks/zoom.py` — webhook_received, meeting_ingested
- `webhooks/recall.py` — webhook_received, meeting_ingested

### Dashboard
- **Production URL**: https://ravishing-patience-production-f793.up.railway.app/dashboard
- **Local URL**: http://localhost:8000/dashboard
- **Auto-refreshes** every 5 seconds
- **Stats cards**: Messages (Discord+SMS breakdown), Tool Uses, Ingested (emails/calls/docs/meetings), Active Agents, Self-Mods, Code Ops, Errors
- **Activity feed**: color-coded action badges, filters by agent/action type/time range
- **Agent sidebar**: config details, tools, standing instructions
- **API endpoints**: `/dashboard/api/stats`, `/dashboard/api/activity`, `/dashboard/api/agents`

## Founders
- Dhiraj Pangal: +19256993247 (Discord: dhirajarcuate)
- 4 part-time founders total

## Current Status (as of 2026-02-15)
- **Discord bot**: WORKING — "Arcuate Chief of Staff#7949" (bot ID: 1471658651491106847)
- **Email identity**: agent1@arcuatehealth.com (Google OAuth, sends and reads from this account)
- **Knowledge base**: 501 emails, 27 Google Docs, 35 ElevenLabs transcripts in ChromaDB + SQLite
- **Agent system**: config-driven with self-modification, code ops, memory, sub-agents, and comprehensive activity tracking
- **Code self-modification**: WORKING — agent can read/edit/deploy its own code via Discord
- **Dashboard**: LIVE at https://ravishing-patience-production-f793.up.railway.app/dashboard
- **Railway deployment**: DEPLOYED AND WORKING — auto-deploys from GitHub on push
- **Local server**: works on localhost:8000
- **SMS via Twilio**: sends from API but Dhiraj doesn't receive texts — use Discord instead

## Communication Channel
**Discord** (primary). Bot responds to:
- DMs to the bot
- @mentions in any channel
- Messages in channels listed in DISCORD_CHANNELS config (default: chief-of-staff, arcuatechat)

## Data Sources
- **Gmail** — authenticated via OAuth as agent1@arcuatehealth.com (token.json locally, GOOGLE_TOKEN_JSON env var on Railway)
- **Google Docs** — same OAuth token, reads all docs in the account
- **ElevenLabs** — AI call transcripts (Conversational AI API). Calls to +16282127401 go through Twilio->ngrok->ElevenLabs voice agent (separate process). Transcripts are synced every 5 minutes by the background scheduler and appear as `call_ingested` events on the dashboard.
- **Zoom** — webhook code built, credentials NOT configured
- **Recall.ai** — webhook + bot dispatch code built, credentials NOT configured. Code handles this gracefully (skips when not configured).

## Voice Calls (628 Number)
Calls to **+16282127401** follow a separate pipeline:
1. Caller dials -> Twilio routes to ngrok tunnel -> ElevenLabs Conversational AI handles the call
2. This is a separate process running locally (don't touch ngrok)
3. Every 5 minutes, the background scheduler (`ingestion/scheduler.py`) syncs ElevenLabs transcripts into the knowledge base
4. These appear on the dashboard as `call_ingested` events with ~5 minute delay
5. For real-time tracking, would need Twilio voice status callbacks (future enhancement)

## Credentials & Local Files (all in repo root, all gitignored)
- `.env` — all API keys and config
- `credentials.json` — Google OAuth client (Desktop app type, project: agents-arcuate)
- `token.json` — Google OAuth refresh token for agent1@arcuatehealth.com (auto-refreshes)
- `token.json.dhiraj.bak` — backup of Dhiraj's old OAuth token (in case you need it)
- `chief_of_staff.db` — SQLite with document metadata + conversation history + activity tracking
- `chroma_data/` — ChromaDB vector embeddings (~33MB)

## API Keys (in .env)
- **Anthropic**: configured (claude-sonnet-4-5-20250929)
- **Twilio**: configured (SID, token, phone +18888854780, also +13102998162, +14155821479)
- **ElevenLabs**: configured
- **Discord**: configured (bot token present)
- **Google OAuth**: configured (credentials.json + token.json, authenticated as agent1@arcuatehealth.com)
- **GitHub**: configured (fine-grained PAT with Contents read/write on arcuate_agents)
- **Zoom**: NOT configured (blank)
- **Recall.ai**: NOT configured (blank)

## GCP Project
- Project ID: `agents-arcuate` (numeric: 550730552191)
- Gmail API: ENABLED
- Google Drive API: ENABLED
- Google Docs API: ENABLED

## Railway Deployment
- **URL**: https://ravishing-patience-production-f793.up.railway.app
- **Dashboard**: https://ravishing-patience-production-f793.up.railway.app/dashboard
- **Status**: DEPLOYED AND WORKING
- Project ID: dac8716b-a213-4da5-a6c8-55c2bef98e96
- GitHub repo connected: pangal-nsgy/arcuate_agents
- Branch: claude/mcp-chrome-extension-BW3zj (auto-deploys on push)
- Env vars configured: ANTHROPIC_API_KEY, TWILIO_*, ELEVENLABS_API_KEY, DISCORD_BOT_TOKEN, CHIEF_EMAIL, FOUNDER_PHONE_NUMBERS, MESSAGING_CHANNEL, CHROMA_PERSIST_DIR, SQLITE_DB_PATH, PORT, GOOGLE_TOKEN_JSON, GITHUB_TOKEN, LOG_FORMAT=json

### Dockerfile Notes
- Uses `python:3.12-slim`
- Source files (`src/`, `agents/`, `agent_memory/`) are copied BEFORE `pip install` — this is critical, otherwise the installed package is empty/stale
- Sets `PYTHONPATH=/app/src`, `AGENTS_DIR=/app/agents`, `AGENT_MEMORY_DIR=/app/agent_memory`

## How to Run Locally
```bash
cd /Users/dhirajpangal/Desktop/arcuate_agents
source venv/bin/activate
PYTHONPATH=src python -m uvicorn chief_of_staff.main:app --host 0.0.0.0 --port 8000
# Dashboard: http://localhost:8000/dashboard
```

## Next Steps (priority order)
1. **Create first sub-agents** — lead_scorer, research_agent, etc. via Discord (agent creates YAML + deploys via code ops)
2. **Add real-time 628 call tracking** — add Twilio voice status callbacks so calls appear instantly on dashboard
3. **Set up Zoom integration** — configure Zoom credentials when ready, webhook code is already built
4. **Consider removing `send_meeting_bot`** from default tools since Recall.ai isn't configured (low priority, code handles gracefully)

## Key Decisions Made
- Discord over SMS/WhatsApp — Twilio SMS wasn't delivering to Dhiraj's phone
- agent1@arcuatehealth.com as email identity — dedicated agent email, not Dhiraj's personal
- Config-driven agents over hardcoded — agents load from YAML, can self-modify
- GitHub REST API for code ops — works from Railway (no git CLI), uses Git Data API for atomic commits
- Raw Anthropic API over Agent SDK — full control over tool loop, better activity tracking, cleaner security model
- File-based memory over DB — readable, git-trackable, simple
- SQLite for activity tracking — same DB, no new dependencies
- Railway over GCP VM — simpler deployment, connects to GitHub, auto-deploys on push
- ChromaDB for vector search — local, no external service needed
- Comprehensive tracking — all 9 files that handle communication/ingestion/webhooks now log to activity table

## Production Hardening (implemented 2026-02-15)

### Async Client
- `core.py` and `discord_bot.py` use `anthropic.AsyncAnthropic` — no sync blocking in the event loop
- Triage calls in Discord are now direct `await` (no `run_in_executor`)

### Timeouts
- **Overall request**: 120s (configurable via `request_timeout` in agent YAML)
- **Per-API-call**: 60s (set in `AsyncAnthropic(timeout=60.0)`)
- **Per-tool**: 30s (enforced via `asyncio.wait_for`)
- On timeout, user gets a friendly message instead of a hang

### Retry Logic (`agent/retry.py`)
- Automatic retry with exponential backoff (1s, 2s, 4s) for transient failures
- Handles: 429 (rate limit, reads retry-after), 500/502/503/529, timeouts, connection errors
- Max 3 retries before re-raising

### Error Handling
- `execute_tool()` never raises — catches all exceptions and returns error strings
- Agent sees error messages and can explain them naturally
- Errors reported to `#bot-errors` Discord channel with full context
- Error reporter: `communication/error_reporter.py`

### Graceful Degradation
- ChromaDB failure: agent proceeds without KB context (logs warning)
- Scheduler crash: `try/except` around each sync iteration, scheduler loop survives failures

### Memory Safety
- Per-agent `asyncio.Lock` for concurrent memory writes (`append_memory_safe()`)

### Structured Logging
- `LOG_FORMAT=json` for Railway (structured JSON output)
- `LOG_FORMAT=text` for local dev (default, human-readable)

### Health Check
- `/health` checks SQLite, ChromaDB, Discord, Anthropic key
- Returns `"ok"` or `"degraded"` with per-subsystem status

## Known Issues
- ngrok has a stale session — don't touch it, runs existing Twilio voice agent for 628 number
- macOS Python needs SSL_CERT_FILE set via certifi (handled in startup code)
- 628 number calls appear on dashboard with ~5 min delay (ElevenLabs transcript sync interval)
- Railway rolling deploys can cause brief overlap where old and new containers run simultaneously (one-time events, resolves in ~30 seconds)
- Railway Docker builds are slow (~3-5 min) — downloads 79MB ChromaDB ONNX model every build
