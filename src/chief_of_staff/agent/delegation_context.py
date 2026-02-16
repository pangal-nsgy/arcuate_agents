"""Delegation depth context for nested delegate_task calls."""

from __future__ import annotations

from contextvars import ContextVar, Token

_DELEGATION_DEPTH: ContextVar[int] = ContextVar("delegation_depth", default=0)


def get_delegation_depth() -> int:
    """Get current nested delegation depth for this execution context."""
    return _DELEGATION_DEPTH.get()


def enter_delegation() -> Token:
    """Increment depth and return token for reset."""
    return _DELEGATION_DEPTH.set(_DELEGATION_DEPTH.get() + 1)


def exit_delegation(token: Token) -> None:
    """Reset depth to prior value."""
    _DELEGATION_DEPTH.reset(token)
