"""Execution lanes for controlling workload concurrency."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

from chief_of_staff.config import settings

T = TypeVar("T")

_main_lane = asyncio.Semaphore(max(1, settings.main_agent_max_concurrency))
_subagent_lane = asyncio.Semaphore(max(1, settings.subagent_max_concurrency))


async def run_main_lane(task: Awaitable[T]) -> T:
    """Run an awaitable under the main agent concurrency lane."""
    async with _main_lane:
        return await task


async def run_subagent_lane(task: Awaitable[T]) -> T:
    """Run an awaitable under the sub-agent concurrency lane."""
    async with _subagent_lane:
        return await task
