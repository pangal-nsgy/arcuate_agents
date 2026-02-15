"""Error reporter — posts formatted errors to #bot-errors Discord channel."""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone

import discord

logger = logging.getLogger(__name__)

BOT_ERRORS_CHANNEL = "bot-errors"


async def report_error(
    bot: discord.Client,
    error_msg: str,
    context: str = "",
    user_msg: str = "",
) -> None:
    """Post a formatted error report to the #bot-errors channel.

    Args:
        bot: The Discord bot client instance.
        error_msg: The error message or traceback string.
        context: Where the error happened (e.g., "#general from UserName").
        user_msg: The user message that triggered the error (truncated).
    """
    channel = _find_errors_channel(bot)
    if channel is None:
        logger.warning(f"#{BOT_ERRORS_CHANNEL} channel not found — cannot report error")
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    # Truncate error message to fit Discord limits
    error_truncated = error_msg[:1500]

    report = (
        f"**Error Report** — {timestamp}\n"
        f"**Context**: {context}\n"
    )
    if user_msg:
        report += f"**Triggering message**: {user_msg[:200]}\n"
    report += f"```\n{error_truncated}\n```"

    try:
        await channel.send(report)
    except Exception as e:
        logger.error(f"Failed to send error report to #{BOT_ERRORS_CHANNEL}: {e}")


def _find_errors_channel(bot: discord.Client) -> discord.TextChannel | None:
    """Find the #bot-errors channel in any connected guild."""
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if channel.name == BOT_ERRORS_CHANNEL:
                return channel
    return None
