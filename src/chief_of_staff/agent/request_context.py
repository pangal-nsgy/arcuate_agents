"""Per-request context shared across tool calls in an agent turn."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass
class RequestContext:
    channel: str = ""
    user_id: str = ""
    session_id: str = ""


_REQUEST_CONTEXT: ContextVar[RequestContext] = ContextVar(
    "request_context",
    default=RequestContext(),
)


def set_request_context(channel: str, user_id: str, session_id: str) -> Token:
    """Set request context for the current async execution context."""
    return _REQUEST_CONTEXT.set(
        RequestContext(channel=channel, user_id=user_id, session_id=session_id)
    )


def get_request_context() -> RequestContext:
    """Get current request context."""
    return _REQUEST_CONTEXT.get()


def reset_request_context(token: Token) -> None:
    """Reset request context to previous state."""
    _REQUEST_CONTEXT.reset(token)
