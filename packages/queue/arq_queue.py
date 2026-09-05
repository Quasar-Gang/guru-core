"""ARQ-on-Redis implementation of ``QueuePort``."""

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from arq.jobs import Job
from arq.jobs import JobStatus as ArqJobStatus

from packages.queue.jobs import (
    API_WORKER_QUEUE,
    ENGINE_WORKER_QUEUE,
    WORKER_QUEUE_BY_JOB,
    JobPayload,
)
from packages.queue.ports import JobHandle, JobStatus

__all__ = ["ArqQueue"]


class ArqQueue:
    def __init__(self, redis_url: str) -> None:
        self._settings = RedisSettings.from_dsn(redis_url)
        self._pool: ArqRedis | None = None

    async def _get_pool(self) -> ArqRedis:
        if self._pool is None:
            self._pool = await create_pool(self._settings)
        return self._pool

    async def enqueue(self, payload: JobPayload) -> JobHandle:
        pool = await self._get_pool()
        queue_name = payload.queue_name()
        job = await pool.enqueue_job(
            queue_name,
            payload.model_dump(mode="json"),
            _queue_name=WORKER_QUEUE_BY_JOB[queue_name],
        )
        if job is None:  # pragma: no cover - only on explicit job-id collision
            raise RuntimeError(f"could not enqueue job on {queue_name}")
        return JobHandle(job_id=job.job_id, queue=queue_name)

    async def status(self, job_id: str) -> JobStatus | None:
        pool = await self._get_pool()
        # A job id alone does not say which list it went to, so check both.
        for queue in (API_WORKER_QUEUE, ENGINE_WORKER_QUEUE):
            status = await self._status_on(pool, job_id, queue)
            if status is not None:
                return status
        return None

    async def _status_on(self, pool: ArqRedis, job_id: str, queue: str) -> JobStatus | None:
        job = Job(job_id, pool, _queue_name=queue)
        arq_status = await job.status()
        if arq_status is ArqJobStatus.not_found:
            return None
        if arq_status is ArqJobStatus.in_progress:
            return JobStatus.running
        if arq_status is ArqJobStatus.complete:
            info = await job.result_info()
            if info is not None and not info.success:
                return JobStatus.failed
            return JobStatus.done
        return JobStatus.queued

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None
