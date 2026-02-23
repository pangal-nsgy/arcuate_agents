"""Twilio webhook handlers for incoming SMS and WhatsApp messages."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Form, Request, Response
from twilio.request_validator import RequestValidator

from chief_of_staff.agent.core import get_agent
from chief_of_staff.agent.rails import get_rails
from chief_of_staff.agent.activity import log_activity, SMS_RECEIVED, SMS_SENT, ERROR
from chief_of_staff.communication.sms import send_sms
from chief_of_staff.communication.control_commands import handle_control_message
from chief_of_staff.config import settings
from chief_of_staff.knowledge.database import get_recent_conversations, log_conversation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/twilio", tags=["twilio"])


def _strip_whatsapp_prefix(phone: str) -> str:
    """Strip whatsapp: prefix for clean storage, keep raw E.164 number."""
    return phone.replace("whatsapp:", "")


@router.post("/sms")
async def incoming_sms(
    request: Request,
    From: str = Form(...),
    Body: str = Form(...),
    MessageSid: str = Form(""),
) -> Response:
    """Handle incoming SMS or WhatsApp message from Twilio."""
    if settings.twilio_auth_token:
        validator = RequestValidator(settings.twilio_auth_token)
        form_data = dict(await request.form())
        url = str(request.url).replace("http://", "https://")
        signature = request.headers.get("X-Twilio-Signature", "")
        if not validator.validate(url, form_data, signature):
            logger.warning(f"Invalid Twilio signature from {From}")
            return Response(
                content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
                media_type="text/xml",
                status_code=403,
            )

    raw_from = From
    clean_phone = _strip_whatsapp_prefix(From)
    is_whatsapp = raw_from.startswith("whatsapp:")
    channel_type = "whatsapp" if is_whatsapp else "sms"

    logger.info(f"Incoming {channel_type} from {clean_phone}: {Body[:100]}...")

    control_result = handle_control_message(clean_phone, Body)
    if control_result.handled:
        await send_sms(to=clean_phone, body=control_result.response)
        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
            media_type="text/xml",
        )

    # Track incoming message
    log_activity(
        agent_name="chief_of_staff",
        action_type=SMS_RECEIVED,
        action_detail=Body[:500],
        channel=channel_type,
        user_id=clean_phone,
        metadata={"message_sid": MessageSid, "is_whatsapp": is_whatsapp},
    )

    # Log the inbound message
    conv_id = str(uuid.uuid4())
    log_conversation(
        conv_id=conv_id,
        founder_phone=clean_phone,
        direction="inbound",
        message=Body,
    )

    # Build conversation history from recent messages
    recent = get_recent_conversations(clean_phone, limit=10)
    history = []
    for msg in reversed(recent):
        role = "assistant" if msg.get("direction") == "outbound" else "user"
        history.append({"role": role, "content": msg["message"]})

    rails = get_rails()
    if not rails.llm_enabled:
        response_text = (
            "LLM handling is currently paused for safety. "
            "Send '/resume llm' from an authorized phone when ready."
        )
    else:
        # Get agent response
        try:
            agent = get_agent()
            response_text = await agent.respond(
                user_message=Body,
                conversation_history=history[:-1],
                channel=channel_type,
                user_id=clean_phone,
            )
        except Exception as e:
            logger.error(f"Agent failed on {channel_type} from {clean_phone}: {e}")
            log_activity(
                agent_name="chief_of_staff",
                action_type=ERROR,
                action_detail=f"Agent failed on {channel_type}: {e}",
                channel=channel_type,
                user_id=clean_phone,
            )
            response_text = "Something went wrong — I'll get back to you."

    # Log the response
    log_conversation(
        conv_id=str(uuid.uuid4()),
        founder_phone=clean_phone,
        direction="outbound",
        message=response_text,
    )

    # Track outbound response
    log_activity(
        agent_name="chief_of_staff",
        action_type=SMS_SENT,
        action_detail=response_text[:500],
        channel=channel_type,
        user_id=clean_phone,
    )

    # Send response back via the same channel
    await send_sms(to=clean_phone, body=response_text)

    return Response(
        content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        media_type="text/xml",
    )
