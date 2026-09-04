# packages/queue

## What it owns

- Defines every cross-service **queue payload** (`jobs.py`). All of them are Pydantic v2, frozen and
  `extra="forbid"`, with a version suffix in the name (`PlanGenerateJobV1`).
- Each payload declares its own queue through the `queue_name()` classmethod; `JOB_REGISTRY` is the
  reverse lookup from queue name to payload class, which workers use to rebuild a payload.
- Provides two `QueuePort` implementations: `ArqQueue` (ARQ on Redis, for production) and
  `InMemoryQueue` (for tests, with a `drain()` that runs jobs synchronously).
- Provides `run_worker(redis_url, handlers)`: starts an ARQ worker that turns the raw dict on the
  queue back into the Pydantic model named by `JOB_REGISTRY` before handing it to a handler.

The five queues today: `import.parse`, `plan.generate`, `plan.continue`, `plan.revise`, `export.push`.

## The ports it exposes

- `QueuePort` (Protocol)
  - `async enqueue(payload: JobPayload) -> JobHandle`
  - `async status(job_id: str) -> JobStatus | None`
- Supporting types: `JobPayload`, `JobHandle`, `JobStatus`, `JOB_REGISTRY` and the five `*JobV1` payloads.
- Implementations: `ArqQueue(redis_url)` (plus `close()`), `InMemoryQueue()` (plus `enqueued` and `drain(handlers)`).
- Runtime helper: `run_worker(redis_url, handlers)`.

## What it does not do

- **No business logic.** Job handlers are supplied and injected by each service's application layer;
  this package only delivers and rebuilds payloads.
- **It is not the source of truth for job state.** That lives in PostgreSQL; `status()` is only the
  queue's own live view, and flushing Redis must never lose data.
- No scheduling (cron), no retry policy configuration, no dead-letter management.
- It does not touch the database or HTTP, and it does not decide how worker processes are launched
  (that is `cmd/`).
- `arq` and `redis` appear only in `arq_queue.py` and `worker.py`; no vendor type is visible from
  the port or the payloads.
