"""BlueBubbles messaging helpers (iMessage via BlueBubbles REST)."""

from __future__ import annotations

import logging

import httpx

from chief_of_staff.config import settings

logger = logging.getLogger(__name__)


def _api_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.bluebubbles_password:
        headers["password"] = settings.bluebubbles_password
    return headers


async def send_bluebubbles_text(chat_guid: str, text: str) -> dict[str, object]:
    """Send outbound text message to a BlueBubbles chat guid."""
    if not settings.bluebubbles_server_url:
        raise ValueError("BLUEBUBBLES_SERVER_URL is not configured")

    payload = {
        "chatGuid": chat_guid,
        "message": text,
        "method": "apple-script",
    }
    url = settings.bluebubbles_server_url.rstrip("/") + "/api/v1/message/text"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers=_api_headers())
        resp.raise_for_status()
        data = resp.json()
        logger.info("BlueBubbles send OK for chat %s", chat_guid)
        return data

