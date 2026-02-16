"""Configuration and settings for the Chief of Staff agent."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5-20250929"

    # Twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # ElevenLabs
    elevenlabs_api_key: str = ""

    # Google
    google_credentials_path: str = "./credentials.json"
    google_token_path: str = "./token.json"
    google_credentials_json: str = ""  # JSON string (for Railway/Docker — overrides file)
    google_token_json: str = ""  # JSON string (for Railway/Docker — overrides file)

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

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Knowledge store
    chroma_persist_dir: str = "./chroma_data"
    sqlite_db_path: str = "./chief_of_staff.db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
