"""FastAPI application — entry point for the Chief of Staff agent."""

from __future__ import annotations

import json
import logging
import os
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from chief_of_staff.config import settings
from chief_of_staff.knowledge.database import init_db
from chief_of_staff.agent.activity import init_activity_tables
from chief_of_staff.webhooks.twilio import router as twilio_router
from chief_of_staff.webhooks.gmail import router as gmail_router
from chief_of_staff.webhooks.zoom import router as zoom_router
from chief_of_staff.webhooks.recall import router as recall_router
from chief_of_staff.dashboard.routes import router as dashboard_router


# --- Structured logging ---
class JSONFormatter(logging.Formatter):
    """JSON log formatter for structured output on Railway."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


log_format = os.environ.get("LOG_FORMAT", "text")
if log_format == "json":
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    logging.root.handlers = [handler]
    logging.root.setLevel(logging.INFO)
else:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    logger.info("Starting Arcuate Chief of Staff Agent...")
    init_db()
    init_activity_tables()
    logger.info("Database initialized (with activity tracking)")

    # Fix SSL certs on macOS (not needed on Linux/Railway)
    try:
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    except ImportError:
        pass

    import asyncio

    # Start background ingestion scheduler (hourly re-sync, non-blocking)
    from chief_of_staff.ingestion.scheduler import start_scheduler
    start_scheduler()
    logger.info("Background scheduler started")

    # Recover queued/running async sub-agent runs after restarts
    try:
        from chief_of_staff.agent.subagent_runtime import recover_pending_sub_agent_runs
        recovered = recover_pending_sub_agent_runs()
        if recovered:
            logger.info(f"Recovered {recovered} pending sub-agent run(s)")
    except Exception as e:
        logger.error(f"Sub-agent recovery failed: {e}", exc_info=True)

    # Start Discord bot if enabled and configured
    if settings.enable_discord_bot:
        from chief_of_staff.communication.discord_bot import start_discord_bot
        asyncio.create_task(start_discord_bot())
        logger.info("Discord bot task started")
    else:
        logger.info("Discord bot startup disabled (ENABLE_DISCORD_BOT=false)")

    yield
    logger.info("Shutting down Chief of Staff Agent")


app = FastAPI(
    title="Arcuate Chief of Staff",
    description="AI Chief of Staff for Arcuate Health — unified knowledge + communication agent",
    version="0.1.0",
    lifespan=lifespan,
)

# Register webhook routers
app.include_router(twilio_router)
app.include_router(gmail_router)
app.include_router(zoom_router)
app.include_router(recall_router)

# Register dashboard
app.include_router(dashboard_router)


@app.get("/health")
async def health_check():
    """Enhanced health check — checks all subsystems."""
    from chief_of_staff.agent.rails import get_rails

    checks = {}

    # SQLite
    try:
        import sqlite3
        conn = sqlite3.connect(settings.sqlite_db_path)
        conn.execute("SELECT 1")
        conn.close()
        checks["sqlite"] = "ok"
    except Exception as e:
        checks["sqlite"] = f"error: {e}"

    # ChromaDB
    try:
        from chief_of_staff.knowledge.vectordb import get_collection
        collection = get_collection()
        count = collection.count()
        checks["chromadb"] = f"ok ({count} chunks)"
    except Exception as e:
        checks["chromadb"] = f"error: {e}"

    # Discord
    try:
        from chief_of_staff.communication.discord_bot import get_discord_bot
        bot = get_discord_bot()
        if bot.is_ready():
            checks["discord"] = f"ok ({len(bot.guilds)} guilds)"
        else:
            checks["discord"] = "connecting"
    except Exception as e:
        checks["discord"] = f"error: {e}"

    # Anthropic key
    checks["anthropic_key"] = "ok" if settings.anthropic_api_key else "missing"
    rails = get_rails()
    checks["rails"] = {
        "llm_enabled": rails.llm_enabled,
        "command_exec_enabled": rails.command_exec_enabled,
    }

    # Overall status
    has_errors = any("error" in str(v) or v == "missing" for v in checks.values())
    status = "degraded" if has_errors else "ok"

    return {"status": status, **checks}


@app.post("/api/ask")
async def ask_agent(query: str, user_id: str | None = None):
    """Direct API endpoint to ask the Chief of Staff a question."""
    from chief_of_staff.agent.rails import get_rails
    from chief_of_staff.agent.core import get_agent

    rails = get_rails()
    if not rails.llm_enabled:
        return {
            "response": (
                "LLM inbound is paused by runtime rails. "
                "Resume via control command: '/resume llm'."
            )
        }

    agent = get_agent()
    response = await agent.respond(
        user_message=query,
        channel="api",
        user_id=user_id or "api_user",
    )
    return {"response": response}


@app.post("/api/ingest/emails")
async def trigger_email_ingestion(max_results: int = 100, query: str = ""):
    """Manually trigger email ingestion."""
    from chief_of_staff.ingestion.gmail import fetch_and_ingest_emails

    count = fetch_and_ingest_emails(max_results=max_results, query=query)
    return {"emails_ingested": count}


@app.post("/api/ingest/docs")
async def trigger_docs_ingestion(
    folder_id: str | None = None,
    max_results: int = 50,
    async_mode: bool = True,
):
    """Manually trigger Google Docs ingestion."""
    from chief_of_staff.ingestion.gdocs import fetch_and_ingest_docs

    if async_mode:
        async def _job():
            try:
                loop = asyncio.get_event_loop()
                count = await loop.run_in_executor(
                    None,
                    lambda: fetch_and_ingest_docs(folder_id=folder_id, max_results=max_results),
                )
                logger.info(f"Background docs ingestion completed: {count} docs")
            except Exception as e:
                logger.error(f"Background docs ingestion failed: {e}", exc_info=True)

        asyncio.create_task(_job())
        return {
            "status": "accepted",
            "message": "Docs ingestion started in background.",
            "max_results": max_results,
            "folder_id": folder_id or "",
        }

    loop = asyncio.get_event_loop()
    count = await loop.run_in_executor(
        None,
        lambda: fetch_and_ingest_docs(folder_id=folder_id, max_results=max_results),
    )
    return {"docs_ingested": count}


@app.get("/api/ingest/docs/debug")
async def debug_docs_ingestion(max_results: int = 20, run_ingest: bool = False, write: bool = False):
    """Inspect Google Drive visibility for the current OAuth token."""
    from chief_of_staff.ingestion.gdocs import debug_drive_visibility, diagnose_docs_ingestion

    out = debug_drive_visibility(max_results=max_results)
    if run_ingest:
        out["ingest_diagnostics"] = diagnose_docs_ingestion(max_results=max_results, write=write)
    return out


@app.post("/api/ingest/transcripts")
async def trigger_transcript_ingestion(limit: int = 50):
    """Manually trigger ElevenLabs transcript ingestion."""
    from chief_of_staff.ingestion.elevenlabs import fetch_and_ingest_transcripts

    count = await fetch_and_ingest_transcripts(limit=limit)
    return {"transcripts_ingested": count}


@app.post("/api/ingest/meeting")
async def ingest_meeting(
    title: str,
    transcript: str,
    meeting_date: str | None = None,
    attendees: list[str] | None = None,
    platform: str = "zoom",
):
    """Manually ingest a meeting transcript."""
    from chief_of_staff.ingestion.meetings import ingest_meeting_transcript

    doc_id = ingest_meeting_transcript(
        title=title,
        transcript=transcript,
        meeting_date=meeting_date,
        attendees=attendees,
        platform=platform,
    )
    return {"doc_id": doc_id}


@app.post("/api/ingest/zoom")
async def trigger_zoom_ingestion(days_back: int = 30, user_emails: list[str] | None = None):
    """Manually trigger Zoom cloud recording ingestion."""
    from chief_of_staff.ingestion.zoom import fetch_and_ingest_recordings

    count = await fetch_and_ingest_recordings(days_back=days_back, user_emails=user_emails)
    return {"zoom_recordings_ingested": count}


@app.post("/api/meetings/send-bot")
async def send_meeting_bot(
    meeting_url: str,
    meeting_title: str = "",
    bot_name: str = "Arcuate Chief of Staff",
):
    """Send a Recall.ai bot to join and record a meeting."""
    from chief_of_staff.ingestion.recall_bot import dispatch_bot

    result = await dispatch_bot(
        meeting_url=meeting_url,
        meeting_title=meeting_title,
        bot_name=bot_name,
    )
    return {"bot_id": result.get("id"), "status": "dispatched"}


@app.get("/api/meetings/bots")
async def list_meeting_bots(limit: int = 20):
    """List recently deployed meeting bots."""
    from chief_of_staff.ingestion.recall_bot import list_bots

    bots = await list_bots(limit=limit)
    return {"bots": bots}


@app.post("/api/meetings/bots/{bot_id}/ingest")
async def ingest_bot_transcript_endpoint(bot_id: str, meeting_title: str = ""):
    """Manually trigger transcript ingestion for a specific bot."""
    from chief_of_staff.ingestion.recall_bot import ingest_bot_transcript

    doc_id = await ingest_bot_transcript(bot_id=bot_id, meeting_title=meeting_title)
    return {"doc_id": doc_id}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port)
