"""Configuration and settings for the Chief of Staff agent."""

from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5-20250929"

    # OpenAI (overflow — continues when Anthropic hits max_iterations)
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1"
    overflow_enabled: bool = True
    overflow_iterations: int = 10

    # Twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # BlueBubbles (iMessage primary channel)
    bluebubbles_enabled: bool = False
    bluebubbles_server_url: str = ""
    bluebubbles_password: str = ""
    bluebubbles_webhook_secret: str = ""
    bluebubbles_dm_policy: str = "pairing"  # pairing | allowlist | open
    bluebubbles_allow_from: list[str] = []
    bluebubbles_group_policy: str = "allowlist"  # allowlist | open | disabled
    bluebubbles_group_allow_from: list[str] = []
    bluebubbles_require_mention_in_groups: bool = True
    bluebubbles_mention_keywords: list[str] = ["@chief", "chief of staff", "arcuate"]
    bluebubbles_pairing_store_path: str = "./bluebubbles-pairing.json"
    bluebubbles_pairing_code_ttl_minutes: int = 60

    # ElevenLabs
    elevenlabs_api_key: str = ""

    # Google
    google_credentials_path: str = "./credentials.json"
    google_token_path: str = "./token.json"
    google_credentials_json: str = ""  # JSON string (for Railway/Docker — overrides file)
    google_token_json: str = ""  # JSON string (for Railway/Docker — overrides file)
    google_shared_drive_ids: str = ""  # Comma-separated shared drive IDs to include in indexing

    # Zoom (Server-to-Server OAuth)
    zoom_account_id: str = ""
    zoom_client_id: str = ""
    zoom_client_secret: str = ""
    zoom_webhook_secret: str = ""
    zoom_auto_record_internal: bool = True

    # Recall.ai (meeting bot)
    recall_api_key: str = ""

    # Discord
    discord_bot_token: str = ""
    enable_discord_bot: bool = True
    discord_channels: list[str] = ["chief-of-staff", "arcuatechat"]  # bot responds in these channels + DMs + @mentions

    # GitHub (code self-modification)
    github_token: str = ""
    github_repo: str = "pangal-nsgy/arcuate_agents"
    github_branch: str = "dev"

    # Agent config
    chief_email: str = ""
    founder_phone_numbers: list[str] = []
    messaging_channel: str = "whatsapp"  # "sms" or "whatsapp"
    founder_emails: list[str] = []
    email_visibility_mode: str = "cc"  # "cc" or "bcc"
    gmail_pubsub_subscription: str = ""  # expected Pub/Sub subscription for webhook auth
    webhook_base_url: str = "http://localhost:8000"

    # Gmail push notifications
    gmail_watch_topic: str = ""  # Pub/Sub topic for Gmail watch (e.g., projects/agents-arcuate/topics/gmail-push)

    # Discord channels for proactive features
    briefing_channel: str = "chief-of-staff"
    meeting_notes_channel: str = "chief-of-staff"
    team_health_channel: str = "chief-of-staff"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    main_agent_max_concurrency: int = 16
    subagent_max_concurrency: int = 4
    subagent_announce_channel: str = "chief-of-staff"

    # Gateway auth + HTTP tool policy (OpenClaw-style surface)
    gateway_auth_token: str = ""
    exec_approvals_path: str = "./exec-approvals.json"
    gateway_tools_deny: list[str] = [
        "sessions_spawn",
        "sessions_send",
        "gateway",
        "whatsapp_login",
    ]
    gateway_tools_allow: list[str] = []

    # Hooks (OpenClaw-style ingress)
    hooks_enabled: bool = True
    hooks_token: str = ""
    hooks_base_path: str = "/hooks"
    hooks_allow_request_session_key: bool = False
    hooks_default_session_key: str = "hook:ingress"
    hooks_allowed_session_key_prefixes: list[str] = ["hook:"]
    hooks_transforms_dir: str = "./hooks/transforms"
    hooks_mappings: list[dict[str, Any]] = []

    # Usage and cost circuit breakers
    usage_ledger_path: str = "./usage-ledger.json"
    usage_default_action_cost_usd: float = 0.01
    usage_run_budget_usd: float = 0.50
    usage_session_budget_usd: float = 2.00
    usage_day_budget_usd: float = 10.00

    # Voice command execution (meeting transcripts -> task execution)
    voice_exec_enabled: bool = False
    voice_exec_dry_run: bool = True
    voice_command_prefixes: list[str] = ["agent execute", "execute task"]
    voice_allowed_speakers: list[str] = []
    voice_approval_wait_ms: int = 10

    # Runtime rails / kill switches
    llm_inbound_enabled: bool = False
    command_execution_enabled: bool = False
    command_allowed_phones: list[str] = []
    command_allowed_prefixes: list[str] = [
        "pwd",
        "ls",
        "git status",
        "git log --oneline -n 5",
    ]
    command_timeout_seconds: int = 20

    # Knowledge store
    chroma_persist_dir: str = "./chroma_data"
    sqlite_db_path: str = "./chief_of_staff.db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
