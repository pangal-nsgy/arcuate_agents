# Arcuate Chief of Staff Agent

> **This file is the canonical reference for any developer or AI agent working on this codebase.**
> Read this before making changes. If you add a tool, module, or change the architecture, update this file.

## What This Is

AI Chief of Staff for [Arcuate Health](https://arcuatehealth.com) — an agentic outreach company for high-end aesthetic practices (ElevenLabs + Twilio voice calls to practices). The agent ingests all company knowledge (emails, docs, call transcripts, meetings) into a unified knowledge base and lets founders interact via Discord.

**Primary interface**: Discord bot ("Angie" / Arcuate Chief of Staff)
**Deployed at**: Railway (auto-deploys on push to the deploy branch)
**Dashboard**: `/dashboard` on the deployed URL

---

## Quick Start (for developers and AI agents)

```bash
git clone https://github.com/pangal-nsgy/arcuate_agents.git
cd arcuate_agents
python3 -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # Fill in API keys — see .env.example for docs
PYTHONPATH=src uvicorn chief_of_staff.main:app --host 0.0.0.0 --port 8000
```

**Google OAuth** (needed for email/docs): run `python scripts/setup_google_auth.py` and sign in with the agent email. This creates `token.json` locally.

**Tests**: `PYTHONPATH=src pytest tests/ -v`

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  INTERFACES: Discord Bot | SMS (Twilio) | API (/api/ask)    │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│  AGENT CORE (src/chief_of_staff/agent/)                     │
│  core.py      — Async agentic loop (Claude API + tools)     │
│  tools.py     — 17 tool definitions + execute_tool()        │
│  registry.py  — YAML config loader (agents/*.yaml)          │
│  memory.py    — Per-agent persistent memory (.md files)      │
│  activity.py  — Activity tracking (22 types → SQLite)       │
│  retry.py     — Exponential backoff for transient failures   │
│  planner.py   — Multi-step task decomposition               │
│  code_ops.py  — Code self-modification via GitHub REST API   │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│  KNOWLEDGE STORE (src/chief_of_staff/knowledge/)            │
│  store.py     — Unified interface (search, ingest, context) │
│  vectordb.py  — ChromaDB semantic search                    │
│  database.py  — SQLite document metadata                    │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│  INGESTION (src/chief_of_staff/ingestion/)                  │
│  scheduler.py — Background sync every 5 min (crash-safe)    │
│  gmail.py     — Gmail API email ingestion                   │
│  gdocs.py     — Google Docs/Drive ingestion                 │
│  elevenlabs.py— ElevenLabs call transcript ingestion        │
│  zoom.py      — Zoom cloud recording ingestion              │
└─────────────────────────────────────────────────────────────┘
```

**Supporting modules**:
- `src/chief_of_staff/communication/` — Discord bot, SMS, email, error reporter, Google auth
- `src/chief_of_staff/dashboard/` — Live web dashboard (API + embedded SPA)
- `src/chief_of_staff/webhooks/` — Twilio, Gmail push, Zoom, Recall.ai webhooks
- `src/chief_of_staff/config.py` — Pydantic `Settings` (auto-loads from `.env`)
- `src/chief_of_staff/main.py` — FastAPI app entry point + lifespan setup

---

## Directory Structure

```
arcuate_agents/
├── CLAUDE.md                    # THIS FILE — canonical architecture reference
├── README.md                    # Public-facing project overview
├── CONTRIBUTING.md              # Developer setup guide
├── ARCHITECTURE.md              # High-level system design diagram
├── architecture_changelog.yaml  # Architecture change log (tracked on dashboard)
├── pyproject.toml               # Python package config (deps, build)
├── Dockerfile                   # Production Docker image (Python 3.12-slim)
├── railway.toml                 # Railway deployment config
├── .env.example                 # Env var template with full docs
├── .gitignore                   # Excludes .env, credentials, *.db, chroma_data/, venv/
│
├── agents/                      # Agent YAML configs (self-modifiable at runtime)
│   └── chief_of_staff.yaml      # Main agent — system prompt, tools, permissions
│
├── agent_memory/                # Per-agent persistent memory (Markdown files)
│   └── chief_of_staff.md        # Learnings, preferences, patterns
│
├── src/chief_of_staff/          # Main application source
│   ├── __init__.py
│   ├── main.py                  # FastAPI app, lifespan, route registration
│   ├── config.py                # Pydantic Settings (env vars → typed config)
│   ├── agent/                   # Core agent system
│   ├── communication/           # Discord, SMS, email, error reporter
│   ├── knowledge/               # ChromaDB + SQLite knowledge store
│   ├── ingestion/               # Data sync pipeline
│   ├── dashboard/               # Web dashboard (routes + embedded HTML)
│   └── webhooks/                # Incoming webhook handlers
│
├── scripts/                     # Setup and utility scripts
│   ├── setup_google_auth.py     # Run Google OAuth flow
│   ├── validate_credentials.py  # Verify all API keys work
│   └── ingest_initial.py        # One-time historical data ingestion
│
├── tests/                       # Test suite (pytest + pytest-asyncio)
│   ├── conftest.py              # Shared fixtures (mock configs, mock API)
│   ├── test_core.py             # Agent loop tests
│   ├── test_tools.py            # Tool dispatch tests
│   ├── test_retry.py            # Retry logic tests
│   └── test_error_handling.py   # Error wrapping tests
│
├── chroma_data/                 # ChromaDB vector embeddings (gitignored, ~33MB)
├── chief_of_staff.db            # SQLite database (gitignored)
├── credentials.json             # Google OAuth client secret (gitignored)
└── token.json                   # Google OAuth refresh token (gitignored)
```

---

## Environment Variables

All env vars are loaded via Pydantic `Settings` in `src/chief_of_staff/config.py`. The `.env` file is auto-read. See `.env.example` for the complete reference with required/optional markers.

### How env vars work in this project

1. **Primary pattern**: `config.py` defines a `Settings` class using `pydantic-settings`. All fields map to env vars (e.g., `anthropic_api_key` ↔ `ANTHROPIC_API_KEY`). Import and use: `from chief_of_staff.config import settings`.

2. **Direct `os.environ` access** (2 places only):
   - `registry.py`: `AGENTS_DIR` (default: `./agents`)
   - `memory.py`: `AGENT_MEMORY_DIR` (default: `./agent_memory`)

3. **Logging format toggle** in `main.py`: `LOG_FORMAT=json` for Railway, `text` for local.

4. **Google OAuth dual-mode** in `_google_auth.py`:
   - **Local dev**: uses `credentials.json` + `token.json` files
   - **Railway/Docker**: uses `GOOGLE_CREDENTIALS_JSON` + `GOOGLE_TOKEN_JSON` env vars (full JSON strings)

### Adding a new env var

1. Add the field to `Settings` in `config.py` with a sensible default
2. Add it to `.env.example` with a comment explaining what it does
3. If needed on Railway, add it there too (Railway dashboard or `railway variables set`)
4. Use it via `from chief_of_staff.config import settings` — never raw `os.environ` for new vars

### Required vs optional

| Required | What breaks without it |
|----------|----------------------|
| `ANTHROPIC_API_KEY` | Agent can't reason (core loop fails) |
| `DISCORD_BOT_TOKEN` | No Discord interface (primary input channel) |

Everything else degrades gracefully — Twilio tools return errors, ingestion skips, code ops disabled, etc.

---

## Tools (17)

All tools are defined in `src/chief_of_staff/agent/tools.py`. Each tool has a name, description, input schema, and an implementation function. Tools are registered in `TOOL_DEFINITIONS` (list of dicts) and dispatched by `execute_tool(name, input, agent_name)`.

| Tool | Category | Description |
|------|----------|-------------|
| `search_knowledge` | Knowledge | Semantic search across all company data (ChromaDB) |
| `list_recent_emails` | Knowledge | List emails from SQLite DB |
| `search_meetings` | Knowledge | Search meeting transcripts |
| `send_sms` | Communication | WhatsApp/SMS via Twilio |
| `send_email` | Communication | Gmail API (sends from the agent email) |
| `draft_document` | Communication | Create draft docs |
| `send_meeting_bot` | Meetings | Dispatch Recall.ai bot (not configured — degrades gracefully) |
| `update_own_instructions` | Self-Mod | Add/remove/replace standing instructions in YAML |
| `update_system_prompt` | Self-Mod | Rewrite the agent's base system prompt |
| `update_triage_config` | Self-Mod | Change Discord triage prompt + trigger words |
| `remember` | Memory | Store persistent learnings to agent_memory/*.md |
| `recall_memory` | Memory | Search persistent memory |
| `create_sub_agent` | Delegation | Create new agent from YAML config |
| `delegate_task` | Delegation | Send task to sub-agent, get result |
| `read_own_code` | Code Ops | Read any file in the repo via GitHub API |
| `edit_own_code` | Code Ops | Validate syntax + stage a file change |
| `deploy_changes` | Code Ops | Atomic commit of all staged changes → Railway auto-deploy |

Plus `web_search` as a server-side tool (Anthropic built-in, configured in agent YAML).

### Adding a new tool

1. Define the tool dict in `TOOL_DEFINITIONS` in `tools.py` (name, description, input_schema)
2. Add the implementation as an async function in `tools.py`
3. Add a case to the `execute_tool()` dispatcher
4. Add the tool name to the agent's `tools` list in `agents/*.yaml`
5. Update `architecture_changelog.yaml` with the change
6. **Convention**: tools never raise — catch all exceptions and return error strings

---

## Agent System

### Config-driven agents

Each agent is defined in `agents/<name>.yaml` with:
- `name`, `display_name`, `model`, `max_tokens`, `max_iterations`
- `system_prompt` — the agent's personality and instructions
- `tools` — list of tool names the agent can use
- `server_tools` — Anthropic server-side tools (e.g., web_search)
- `permissions` — `can_self_modify`, `can_create_agents`, `can_send_external`, `can_modify_code`
- `standing_instructions` — dynamic list the agent can update at runtime
- `triage_prompt` — template for Discord message triage
- `trigger_words` — keywords that always trigger a response

The registry (`registry.py`) re-reads YAML from disk on every `get(name)` call, so config changes (including self-modifications) take effect immediately.

### Agent loop (core.py)

1. Reload config from YAML (picks up self-modifications)
2. Build system prompt = base prompt + standing instructions + memory context
3. Retrieve KB context via semantic search (graceful degradation if ChromaDB is down)
4. Agentic loop (up to `max_iterations`):
   - Call Claude API with retry
   - Execute any tool_use blocks (30s timeout per tool)
   - Append results, repeat
5. Return final text response
6. Log all activity to SQLite

### Adding a new agent

1. Create `agents/<name>.yaml` following the chief_of_staff.yaml structure
2. The registry auto-discovers it on next request
3. Or use the `create_sub_agent` tool at runtime (creates YAML dynamically)
4. To persist a runtime-created agent across deploys: use `edit_own_code` + `deploy_changes`

---

## Activity Tracking (22 action types)

All activity is logged to the `agent_activity` SQLite table via `log_activity()` in `activity.py`.

**Action types**: `message_received`, `message_sent`, `tool_use`, `knowledge_search`, `web_search`, `config_update`, `memory_write`, `memory_read`, `sub_agent_spawn`, `delegation`, `sms_received`, `sms_sent`, `call_ingested`, `email_ingested`, `doc_ingested`, `meeting_ingested`, `ingestion_sync`, `webhook_received`, `code_read`, `code_edit`, `code_deploy`, `error`

**Files that log activity** (if you add a new communication channel, wire it up here):
- `discord_bot.py` — message_received, message_sent, error
- `webhooks/twilio.py` — sms_received, sms_sent, error
- `communication/sms.py` — sms_sent
- `ingestion/elevenlabs.py` — call_ingested
- `ingestion/scheduler.py` — email_ingested, doc_ingested, ingestion_sync, error
- `webhooks/gmail.py` — webhook_received, email_ingested
- `webhooks/zoom.py` — webhook_received, meeting_ingested
- `webhooks/recall.py` — webhook_received, meeting_ingested

### Adding a new activity type

1. Add the constant to `activity.py`
2. Call `log_activity()` in the relevant handler
3. Add a badge style in `dashboard/routes.py` (CSS `.action-badge.<type>`)
4. Add it to the filter dropdown in the dashboard HTML

---

## Code Self-Modification

The agent can read, edit, and deploy its own source code via GitHub REST API (`code_ops.py`).

**Safety rails**:
- Blocked paths: `.env`, `credentials.json`, `token.json`, `*.db`, `chroma_data/`, `.git/`, `venv/`
- Syntax validation: `ast.parse` for `.py`, `yaml.safe_load` for `.yaml`
- Permission-gated: requires `can_modify_code: true` in agent YAML
- Audit trail: all code ops logged as activity

**Flow**: `read_own_code` → `edit_own_code` (validates + stages) → `deploy_changes` (atomic commit via Git Data API → Railway auto-deploys)

---

## Conventions and Patterns

### Error handling
- **Tools never raise.** `execute_tool()` catches all exceptions and returns error strings. The agent sees the error message and can explain it to the user.
- **API calls retry.** Use `retry_async()` from `retry.py` for any external API call. Handles 429/500/502/503 with exponential backoff (1s, 2s, 4s), max 3 retries.
- **Timeouts at every level.** Overall request: 120s. Per-API-call: 60s. Per-tool: 30s (`asyncio.wait_for`).
- **ChromaDB degrades gracefully.** If the vector store is down, the agent proceeds without KB context (logs a warning).
- **Errors go to Discord.** The error reporter (`error_reporter.py`) posts formatted error reports to the `#bot-errors` Discord channel.

### Async
- **Everything is async.** Use `AsyncAnthropic`, `await` for all I/O. Never call sync-blocking functions in the event loop.
- **Memory writes use locks.** `append_memory_safe()` uses per-agent `asyncio.Lock`.
- **Ingestion scheduler uses `run_in_executor`** for sync functions (Gmail, GDocs SDK).

### Code style
- Python 3.11+. Ruff for linting (`ruff check`).
- Line length: 100.
- Type hints encouraged but not enforced everywhere.
- Tests use `pytest` + `pytest-asyncio`.

### What NOT to do
- **Don't add sync blocking calls** to the event loop. Use `run_in_executor` if wrapping sync code.
- **Don't let tools raise.** Always wrap in try/except, return error strings.
- **Don't hardcode credentials.** All secrets go in `.env` → `config.py` → `settings`.
- **Don't skip activity tracking.** Every user-facing action should call `log_activity()`.
- **Don't modify .env, credentials.json, token.json, *.db via code ops.** These are blocked.
- **Don't touch ngrok.** An existing Twilio voice agent process runs through it.
- **Don't import from `config` at module level if the setting might not be set** — use lazy access.

---

## Dashboard

The dashboard is a single-page app embedded in `dashboard/routes.py` with two tabs:

### Activity Tab (default)
- Live activity feed with color-coded action badges
- Filters: agent, action type, time range
- Stats cards: Messages, Tool Uses, Ingested, Agents, Self-Mod, Errors
- Agent sidebar with config details and standing instructions
- Auto-refreshes every 5 seconds

### System Tab
- Architecture changelog (from `architecture_changelog.yaml`)
- Tool registry with descriptions
- Module overview
- Recent code deployments

### API endpoints
- `GET /dashboard/api/activity` — Activity feed (filterable)
- `GET /dashboard/api/stats` — Aggregate stats
- `GET /dashboard/api/agents` — Agent configs + activity summaries
- `GET /dashboard/api/system` — Architecture info (tools, changelog, modules)

---

## Deployment

### Railway (production)
- **Branch**: pushes to the deploy branch auto-deploy via Railway
- **Dockerfile**: Python 3.12-slim, copies `src/`, `agents/`, `agent_memory/` before `pip install`
- **Persistent volume**: `/app/data` for SQLite DB and ChromaDB
- **Env vars**: configured in Railway dashboard (mirrors `.env` but uses `GOOGLE_TOKEN_JSON` instead of file paths, `LOG_FORMAT=json`)
- **Health check**: `GET /health` — checks SQLite, ChromaDB, Discord, Anthropic key

### Local development
```bash
source venv/bin/activate
PYTHONPATH=src uvicorn chief_of_staff.main:app --host 0.0.0.0 --port 8000
```
- Uses file-based Google OAuth (`credentials.json` + `token.json`)
- `LOG_FORMAT=text` (default, human-readable)
- Dashboard at `http://localhost:8000/dashboard`

### Deploy workflow
```bash
git add <files>
git commit -m "description"
git push origin <deploy-branch>
# Railway auto-deploys in ~3-5 min (Docker build + ChromaDB ONNX download)
```

The agent can also deploy itself via `edit_own_code` + `deploy_changes` tools (Discord).

---

## Testing

```bash
PYTHONPATH=src pytest tests/ -v
```

Tests cover: agent loop (text response, timeout, iteration limit), tool dispatch (known/unknown/error), retry logic (429 handling, backoff, max retries), error wrapping (tools return strings, not exceptions).

### Writing new tests
- Put tests in `tests/test_<module>.py`
- Use fixtures from `conftest.py` (mock configs, mock Anthropic responses)
- Mock external services — never call real APIs in tests
- Use `pytest-asyncio` for async tests (`@pytest.mark.asyncio`)

---

## How to Add Common Things

### New ingestion source
1. Create `src/chief_of_staff/ingestion/<source>.py` with a sync function
2. Call `knowledge_store.ingest()` to store documents
3. Add to the scheduler loop in `scheduler.py` (wrap in `run_in_executor`)
4. Add activity type if needed, wire up `log_activity()`
5. If it has webhooks, add handler in `webhooks/`

### New communication channel
1. Create handler in `src/chief_of_staff/communication/<channel>.py`
2. Wire into `main.py` (route registration, lifespan startup)
3. Add activity types for inbound/outbound messages
4. Add to dashboard filter dropdown and badge styles

### New webhook
1. Create `src/chief_of_staff/webhooks/<service>.py` with an `APIRouter`
2. Register in `main.py`: `app.include_router(router)`
3. Log `webhook_received` activity

### New env var
1. Add field to `Settings` in `config.py`
2. Add to `.env.example`
3. If needed on Railway, set it there
4. Access via `settings.<field_name>`

---

## Current Status

- **Discord bot**: Running — responds to DMs, @mentions, configured channels
- **Email**: Sends/reads as the agent email via Gmail API
- **Knowledge base**: 500+ emails, 27 Google Docs, 35+ ElevenLabs transcripts
- **Code self-modification**: Working — agent can read/edit/deploy via Discord
- **Dashboard**: Live with Activity and System tabs
- **Railway**: Deployed, auto-deploys on push
- **SMS via Twilio**: Functional but unreliable delivery — Discord preferred
- **Zoom/Recall.ai**: Code built, credentials not configured (degrades gracefully)

## Known Issues
- ngrok has a stale session — don't touch it (runs existing Twilio voice agent)
- macOS Python needs `SSL_CERT_FILE` set via certifi (handled in startup code)
- ElevenLabs call transcripts appear on dashboard with ~5 min delay (sync interval)
- Railway Docker builds are slow (~3-5 min) — downloads 79MB ChromaDB ONNX model every build
