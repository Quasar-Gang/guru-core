"""ARQ worker entrypoint for the Engine.

Serves `profile.build`, `direction.run`, `plan.generate` and `reconcile.run`. No business
logic here.
"""

import asyncio

from packages.config import load_dotenv
from packages.logging import configure_logging
from packages.queue import run_worker
from services.engine.container import build_container, create_worker_handlers

if __name__ == "__main__":
    load_dotenv()
    configure_logging("engine")
    container = build_container()
    asyncio.run(run_worker(container.settings.redis_url, create_worker_handlers(container)))
