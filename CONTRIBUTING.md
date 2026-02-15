# Contributing to Arcuate Chief of Staff Agent

## Quick Start

```bash
# Clone the repo
git clone https://github.com/pangal-nsgy/arcuate_agents.git
cd arcuate_agents

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Copy and fill in environment variables
cp .env.example .env
# Edit .env with your API keys (at minimum: ANTHROPIC_API_KEY, DISCORD_BOT_TOKEN)

# Run locally
PYTHONPATH=src python -m uvicorn chief_of_staff.main:app --host 0.0.0.0 --port 8000
```

Dashboard: http://localhost:8000/dashboard
Health check: http://localhost:8000/health

## Code Structure

See `CLAUDE.md` for full architecture docs. Key directories:

```
src/chief_of_staff/
  agent/          # Agent loop, tools, config, memory, retry logic
  communication/  # Discord bot, SMS, email, error reporter
  knowledge/      # ChromaDB vector search + SQLite metadata
  ingestion/      # Gmail, GDocs, ElevenLabs, Zoom data sync
  dashboard/      # Live activity dashboard
  webhooks/       # Twilio, Gmail push, Zoom, Recall.ai
agents/           # YAML agent configs (self-modifiable)
agent_memory/     # Persistent per-agent memory files
tests/            # Test suite
```

## Error Handling Patterns

- **Tools never raise** `execute_tool()` catches all exceptions and returns error strings. The agent sees the error and explains it naturally.
- **API calls retry** `retry_async()` handles 429/500/502/503 with exponential backoff (1s, 2s, 4s).
- **Timeouts everywhere** Overall request: 120s. Per-API-call: 60s. Per-tool: 30s.
- **ChromaDB degrades gracefully** If the vector store is down, the agent proceeds without KB context.
- **Errors go to #bot-errors** Discord channel gets formatted error reports with context.

## Running Tests

```bash
pytest tests/ -v
```

## Deployment

Push to the `claude/mcp-chrome-extension-BW3zj` branch. Railway auto-deploys from GitHub pushes.

```bash
git push origin claude/mcp-chrome-extension-BW3zj
```

Railway dashboard: https://railway.app (project ID: dac8716b-a213-4da5-a6c8-55c2bef98e96)

## Environment Variables

Railway has all env vars configured. For local development, copy `.env.example` to `.env` and fill in the values. See `.env.example` for descriptions of each variable.

Key difference: Railway uses `GOOGLE_TOKEN_JSON` (full JSON string) while local dev uses `token.json` (file path).

Set `LOG_FORMAT=json` on Railway for structured logging, or leave as `text` for local dev.
