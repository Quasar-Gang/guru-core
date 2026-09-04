"""ARQ worker entrypoint for the Plan Engine (plan.generate / continue / revise).

No business logic here.
"""

import asyncio

from packages.logging import configure_logging
from packages.queue import run_worker
from services.plan_engine.container import build_container, create_worker_handlers

if __name__ == "__main__":
    configure_logging("plan-engine")
    container = build_container()
    asyncio.run(run_worker(container.settings.redis_url, create_worker_handlers(container)))
