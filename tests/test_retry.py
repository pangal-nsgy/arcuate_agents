"""Tests for retry logic with exponential backoff."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import anthropic
from chief_of_staff.agent.retry import retry_async


@pytest.mark.asyncio
async def test_success_on_first_try():
    """Function that succeeds immediately returns the result."""
    func = AsyncMock(return_value="ok")
    result = await retry_async(func, max_retries=3, base_delay=0.01)
    assert result == "ok"
    assert func.call_count == 1


@pytest.mark.asyncio
async def test_retry_on_rate_limit():
    """429 rate limit error gets retried."""
    response = MagicMock()
    response.status_code = 429
    response.headers = {}

    rate_limit_error = anthropic.RateLimitError(
        message="rate limited",
        response=response,
        body=None,
    )

    func = AsyncMock(side_effect=[rate_limit_error, rate_limit_error, "ok"])
    result = await retry_async(func, max_retries=3, base_delay=0.01)
    assert result == "ok"
    assert func.call_count == 3


@pytest.mark.asyncio
async def test_retry_max_exceeded():
    """Exhausted retries re-raise the exception."""
    response = MagicMock()
    response.status_code = 429
    response.headers = {}

    rate_limit_error = anthropic.RateLimitError(
        message="rate limited",
        response=response,
        body=None,
    )

    func = AsyncMock(side_effect=rate_limit_error)
    with pytest.raises(anthropic.RateLimitError):
        await retry_async(func, max_retries=2, base_delay=0.01)
    assert func.call_count == 3  # initial + 2 retries


@pytest.mark.asyncio
async def test_retry_on_timeout():
    """TimeoutError gets retried."""
    func = AsyncMock(side_effect=[asyncio.TimeoutError(), "ok"])
    result = await retry_async(func, max_retries=3, base_delay=0.01)
    assert result == "ok"
    assert func.call_count == 2


@pytest.mark.asyncio
async def test_non_retryable_error_raises_immediately():
    """Non-retryable errors (e.g., 400 bad request) are not retried."""
    response = MagicMock()
    response.status_code = 400
    response.headers = {}

    error = anthropic.BadRequestError(
        message="bad request",
        response=response,
        body=None,
    )

    func = AsyncMock(side_effect=error)
    with pytest.raises(anthropic.BadRequestError):
        await retry_async(func, max_retries=3, base_delay=0.01)
    assert func.call_count == 1  # no retries
