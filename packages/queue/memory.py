"""In-memory queue for unit and application tests: no Redis, no background loop."""

from collections.abc import Awaitable, Callable, Mapping
from uuid import uuid4

from packages.queue.jobs import JobPayload
from packages.queue.ports import JobHandle, JobStatus

__all__ = ["InMemoryQueue"]

Handler = Callable[[JobPayload], Awaitable[None]]


class InMemoryQueue:
    def __init__(self) -> None:
        self.enqueued: list[JobPayload] = []
        self._job_ids: list[str] = []
        self._statuses: dict[str, JobStatus] = {}

    async def enqueue(self, payload: JobPayload) -> JobHandle:
        job_id = uuid4().hex
        self.enqueued.append(payload)
        self._job_ids.append(job_id)
        self._statuses[job_id] = JobStatus.queued
        return JobHandle(job_id=job_id, queue=payload.queue_name())

    async def status(self, job_id: str) -> JobStatus | None:
        return self._statuses.get(job_id)

    async def drain(self, handlers: Mapping[str, Handler]) -> None:
        """Run every pending payload in FIFO order, then clear the queue."""
        pending = list(zip(self._job_ids, self.enqueued, strict=True))
        self.enqueued.clear()
        self._job_ids.clear()
        for job_id, payload in pending:
            handler = handlers.get(payload.queue_name())
            if handler is None:
                self._statuses[job_id] = JobStatus.failed
                continue
            self._statuses[job_id] = JobStatus.running
            try:
                await handler(payload)
            except Exception:
                self._statuses[job_id] = JobStatus.failed
                raise
            self._statuses[job_id] = JobStatus.done
