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

### Collaboration Workflow (AI-Gated Deploys)

Multiple developers (and their AI agents) can push freely — Opus 4.6 reviews everything before it hits production:

```
Push to dev  →  Linter → Tests → Build → Opus 4.6 → Staging check → Deploy → Discord
                                                        ↓ (rejected)
                                                   Discord: "BLOCKED — here's why"

Open PR to dev  →  Same validation  →  Opus 4.6 auto-merges PR  →  Triggers deploy
```

1. **Push to `dev`** (direct) or **open a PR** — never push directly to the deploy branch
2. **Full validation pipeline**: linter → pytest → build check → Opus 4.6 review → staging health check
3. **PRs auto-merge** — if Opus 4.6 approves, the PR is squash-merged automatically (no manual review needed)
4. **If approved** — auto-merges to deploy branch, Railway auto-deploys
5. **If rejected** — Discord notification in #agent-building with what's wrong
6. **Staging environment** — every push to `dev` deploys to staging first; Guardian verifies `/health` before allowing production deploy
7. **Pre-push hook** — runs consistency linter locally before push (install: `bash scripts/install-hooks.sh`)

See [`CLAUDE.md`](CLAUDE.md) for full architecture docs, conventions, and "how to add X" guides.

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

- **Multi-agent workforce** — COS orchestrator + specialist agents (Onboarding Specialist), with skill-based tool loading
- **7 reusable skill modules, 17 tools** — knowledge, communication, meetings, self-mod, memory, delegation, code ops
- **Full company knowledge base** — 500+ emails, Google Docs, ElevenLabs call transcripts, meeting notes in ChromaDB + SQLite
- **Discord interface** — single bot, multi-agent routing via @mention, trigger words, or COS default
- **Email** — sends and reads email as agent1@arcuatehealth.com via Gmail API
- **Self-modification** — agent can update its own instructions, system prompt, and Discord triage behavior
- **Code self-modification** — agent can read, edit, and deploy its own source code via GitHub API, triggering Railway auto-deploy
- **Persistent memory** — per-agent memory, persists key facts and patterns across conversations
- **Activity dashboard** — live web dashboard with Activity tab (22 action types) and System tab (architecture changelog, tool registry)
- **Background ingestion** — syncs emails, docs, and call transcripts every 5 minutes
- **Production hardened** — async throughout, retry with backoff, timeouts at every level, structured error handling

## Agent Workforce

| Agent | Discord Name | Skills | Role |
|-------|-------------|--------|------|
| Chief of Staff | @angie | knowledge, memory, delegation, self_mod, code_ops | Orchestrator — delegates to specialists |
| Onboarding Specialist | @onboarding | knowledge, communication, memory | New practice onboarding |

## Architecture

```
src/chief_of_staff/
  agent/          # Agent loop, router, skill modules, activity tracking, code ops
    skills/       # 7 reusable skill modules (17 tools total)
    router.py     # Multi-agent message routing
  dashboard/      # Web dashboard — Activity tab + System tab
  communication/  # Discord bot (multi-agent), SMS, email, error reporter
  ingestion/      # Gmail, Google Docs, ElevenLabs, Zoom, background scheduler
  knowledge/      # ChromaDB vector search + SQLite metadata
  webhooks/       # Twilio, Gmail push, Zoom, Recall.ai
agents/           # YAML agent configs (self-modifiable at runtime)
agent_memory/     # Persistent per-agent memory files
tests/            # Test suite (63 tests)
```

See [CLAUDE.md](CLAUDE.md) for the full architecture reference.

## Deployment

Deployed on **Railway** with auto-deploy from GitHub pushes. The agent can also deploy itself via Discord (code self-modification tools).

## License

Private — Arcuate Health internal use only.
