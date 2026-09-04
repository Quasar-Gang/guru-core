"""Queue port: enqueue a versioned payload, ask about a job's status."""

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel

from packages.queue.jobs import JobPayload

__all__ = ["JobHandle", "JobStatus", "QueuePort"]


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class JobHandle(BaseModel):
    job_id: str
    queue: str


class QueuePort(Protocol):
    async def enqueue(self, payload: JobPayload) -> JobHandle: ...

    async def status(self, job_id: str) -> JobStatus | None: ...
