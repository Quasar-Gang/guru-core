"""Report the state of one background job."""

from pydantic import BaseModel

from packages.cache import CachePort
from packages.queue import QueuePort

__all__ = ["GetJob", "JobView", "STATUS_UNKNOWN", "job_cache_key"]

#: Nothing knows about this job any more: it never existed, or its record has expired.
STATUS_UNKNOWN = "unknown"


def job_cache_key(job_id: str) -> str:
    return f"job:{job_id}:status"


class JobView(BaseModel):
    job_id: str
    status: str


class GetJob:
    """Cache first, queue second.

    Redis is only ever a cache: flushing it must
    never lose a job, so a miss falls back to the queue's own record. When that has expired
    too, the answer is `unknown` — for the MVP the caller is expected to fall back to
    `GET /v1/direction/runs/latest` or `GET /v1/plans/{id}`, whose authority is the row in
    PostgreSQL.
    """

    def __init__(self, cache: CachePort, queue: QueuePort) -> None:
        self._cache = cache
        self._queue = queue

    async def __call__(self, job_id: str) -> JobView:
        cached = await self._cache.get(job_cache_key(job_id))
        if cached is not None:
            return JobView(job_id=job_id, status=cached)
        status = await self._queue.status(job_id)
        return JobView(job_id=job_id, status=status.value if status is not None else STATUS_UNKNOWN)
