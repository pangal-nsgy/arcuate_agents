# Arcuate Chief of Staff Agent

AI Chief of Staff for [Arcuate Health](https://arcuatehealth.com) — an agentic outreach company for high-end aesthetic practices. The agent ingests all company knowledge (emails, docs, call transcripts, meetings) and lets founders interact with it via Discord.

## For AI Agents (Claude Code, Cursor, etc.)

**Read [`CLAUDE.md`](CLAUDE.md) first.** It is the canonical reference for architecture, conventions, env vars, tools, and how to add things. Everything you need to contribute is there.

## For Developers

### Quick Start

```bash
git clone https://github.com/pangal-nsgy/arcuate_agents.git
cd arcuate_agents
python3 -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # Fill in API keys — see .env.example for required/optional docs
```

**Minimum to run**: `ANTHROPIC_API_KEY` + `DISCORD_BOT_TOKEN` in `.env`. Everything else degrades gracefully.

**Google OAuth** (for email/docs): `python scripts/setup_google_auth.py`

**Run locally**:
```bash
PYTHONPATH=src uvicorn chief_of_staff.main:app --host 0.0.0.0 --port 8000
```

- Dashboard: http://localhost:8000/dashboard
- Health check: http://localhost:8000/health

**Run tests**:
```bash
PYTHONPATH=src pytest tests/ -v
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for full developer setup, and [SETUP.md](SETUP.md) for first-time credential setup (Google OAuth, Twilio, Zoom).

### Collaboration Workflow

Multiple developers (and their AI agents) can work on this repo simultaneously:

1. **Read `CLAUDE.md`** — it has the architecture, conventions, and "how to add X" guides
2. **Check `.env.example`** — all env vars documented with required/optional markers
3. **Check the dashboard System tab** — shows architecture changelog, tool registry, recent deploys
4. **When you change the architecture** — update `CLAUDE.md` and add an entry to `architecture_changelog.yaml`
5. **Deploy** — push to the deploy branch, Railway auto-deploys

### Key Files for Onboarding

| File | Purpose |
|------|---------|
| [`CLAUDE.md`](CLAUDE.md) | **Start here** — canonical architecture, conventions, env vars, how-to guides |
| [`.env.example`](.env.example) | All env vars with required/optional markers and descriptions |
| [`architecture_changelog.yaml`](architecture_changelog.yaml) | Architecture change log (displayed on dashboard System tab) |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Developer setup, error handling patterns, deploy workflow |
| [`SETUP.md`](SETUP.md) | First-time credential setup (Google OAuth, Twilio, Zoom) |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | High-level system design diagram |

## Features

- **Full company knowledge base** — 500+ emails, Google Docs, ElevenLabs call transcripts, meeting notes in ChromaDB + SQLite
- **Discord interface** — chat with the agent in Discord DMs, @mentions, or dedicated channels
- **Email** — sends and reads email as agent1@arcuatehealth.com via Gmail API
- **17 tools** — knowledge search, email, SMS, document drafting, meeting bots, web search
- **Self-modification** — agent can update its own instructions, system prompt, and Discord triage behavior
- **Code self-modification** — agent can read, edit, and deploy its own source code via GitHub API, triggering Railway auto-deploy
- **Persistent memory** — remembers key facts, preferences, and patterns across conversations
- **Sub-agent system** — create and delegate to specialized sub-agents, persist them via code ops
- **Activity dashboard** — live web dashboard with Activity tab (22 action types) and System tab (architecture changelog, tool registry)
- **Background ingestion** — syncs emails, docs, and call transcripts every 5 minutes
- **Production hardened** — async throughout, retry with backoff, timeouts at every level, structured error handling

## Architecture

```
src/chief_of_staff/
  agent/          # Agent loop, 17 tools, retry, activity tracking (22 types), code ops, memory
  dashboard/      # Web dashboard — Activity tab + System tab (architecture changelog)
  communication/  # Discord bot, SMS (Twilio), email (Gmail API), error reporter
  ingestion/      # Gmail, Google Docs, ElevenLabs, Zoom, background scheduler
  knowledge/      # ChromaDB vector search + SQLite metadata
  webhooks/       # Twilio, Gmail push, Zoom, Recall.ai
agents/           # YAML agent configs (self-modifiable at runtime)
agent_memory/     # Persistent per-agent memory files
tests/            # Test suite (16 tests)
```

See [CLAUDE.md](CLAUDE.md) for the full architecture reference.

## Deployment

Deployed on **Railway** with auto-deploy from GitHub pushes. The agent can also deploy itself via Discord (code self-modification tools).

## License

Private — Arcuate Health internal use only.
