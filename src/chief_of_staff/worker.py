"""Background worker entrypoint for non-HTTP scheduled jobs."""

from __future__ import annotations

import asyncio
import logging

from chief_of_staff.agent.activity import init_activity_tables
from chief_of_staff.knowledge.database import init_db
from chief_of_staff.ingestion.scheduler import start_scheduler


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _run_worker() -> None:
    init_db()
    init_activity_tables()
    start_scheduler()
    logger.info("Worker started: scheduler loop active")
    while True:
        await asyncio.sleep(3600)


def main() -> None:
    asyncio.run(_run_worker())


if __name__ == "__main__":
    main()

