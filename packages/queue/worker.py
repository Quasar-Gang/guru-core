"""ARQ worker runner: turns raw queue payloads back into Pydantic models."""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from arq.connections import RedisSettings
from arq.worker import Function, Worker, func

from packages.queue.jobs import JOB_REGISTRY, JobPayload

__all__ = ["run_worker"]

Handler = Callable[[JobPayload], Awaitable[None]]


def _make_function(queue_name: str, handler: Handler) -> Function:
    payload_cls = JOB_REGISTRY[queue_name]

    async def run(ctx: dict[Any, Any], raw: dict[str, Any]) -> None:
        await handler(payload_cls.model_validate(raw))

    return func(run, name=queue_name)


async def run_worker(redis_url: str, handlers: Mapping[str, Handler]) -> None:
    """Serve ``handlers`` (queue name -> coroutine) until the process is stopped."""
    unknown = sorted(set(handlers) - set(JOB_REGISTRY))
    if unknown:
        raise ValueError(f"unknown queue names: {', '.join(unknown)}")
    functions = [_make_function(name, handler) for name, handler in handlers.items()]
    worker = Worker(
        functions=functions,
        redis_settings=RedisSettings.from_dsn(redis_url),
        handle_signals=False,
    )
    try:
        await worker.async_run()
    finally:
        await worker.close()
