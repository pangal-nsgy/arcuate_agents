"""Per-request context shared across tool calls in an agent turn."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass, field


# Minimum interval between progress messages to avoid flooding Discord
_PROGRESS_MIN_INTERVAL = 2.0


@dataclass
class RequestContext:
    channel: str = ""
    user_id: str = ""
    session_id: str = ""
    progress_callback: Callable[[str], Awaitable[None]] | None = None
    _last_progress_time: float = 0.0


_REQUEST_CONTEXT: ContextVar[RequestContext] = ContextVar(
    "request_context",
    default=RequestContext(),
)


def set_request_context(
    channel: str,
    user_id: str,
    session_id: str,
    progress_callback: Callable[[str], Awaitable[None]] | None = None,
) -> Token:
    """Set request context for the current async execution context."""
    return _REQUEST_CONTEXT.set(
        RequestContext(
            channel=channel,
            user_id=user_id,
            session_id=session_id,
            progress_callback=progress_callback,
        )
    )


def get_request_context() -> RequestContext:
    """Get current request context."""
    return _REQUEST_CONTEXT.get()


def reset_request_context(token: Token) -> None:
    """Reset request context to previous state."""
    _REQUEST_CONTEXT.reset(token)


async def emit_progress(message: str) -> None:
    """Send a progress update to the originating channel (if callback is set).

    Throttled to at most one message per _PROGRESS_MIN_INTERVAL seconds.
    Errors are silently swallowed — progress must never break the main flow.
    """
    ctx = get_request_context()
    if not ctx.progress_callback:
        return
    now = time.time()
    if now - ctx._last_progress_time < _PROGRESS_MIN_INTERVAL:
        return
    ctx._last_progress_time = now
    try:
        await ctx.progress_callback(message)
    except Exception:
        pass
