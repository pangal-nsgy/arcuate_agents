"""Retry logic with exponential backoff for transient API failures."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

import anthropic

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}


async def retry_async(
    func: Callable[..., Any],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    **kwargs: Any,
) -> Any:
    """Call an async function with retry on transient errors.

    Handles:
    - anthropic.RateLimitError (429) — reads retry-after header
    - anthropic.APIStatusError with retryable status codes (500, 502, 503, 529)
    - asyncio.TimeoutError
    - ConnectionError
    """
    last_exception: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except anthropic.RateLimitError as e:
            last_exception = e
            if attempt >= max_retries:
                raise
            # Try to read retry-after from response headers
            delay = base_delay * (2 ** attempt)
            retry_after = getattr(e.response, "headers", {}).get("retry-after")
            if retry_after:
                try:
                    delay = max(delay, float(retry_after))
                except (ValueError, TypeError):
                    pass
            logger.warning(f"Rate limited (attempt {attempt + 1}/{max_retries + 1}), retrying in {delay:.1f}s")
            await asyncio.sleep(delay)
        except anthropic.APIStatusError as e:
            last_exception = e
            if e.status_code not in RETRYABLE_STATUS_CODES or attempt >= max_retries:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(f"API error {e.status_code} (attempt {attempt + 1}/{max_retries + 1}), retrying in {delay:.1f}s")
            await asyncio.sleep(delay)
        except (asyncio.TimeoutError, ConnectionError) as e:
            last_exception = e
            if attempt >= max_retries:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(f"{type(e).__name__} (attempt {attempt + 1}/{max_retries + 1}), retrying in {delay:.1f}s")
            await asyncio.sleep(delay)

    # Should not reach here, but just in case
    raise last_exception  # type: ignore[misc]
