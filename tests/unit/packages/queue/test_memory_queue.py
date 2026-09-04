from uuid import uuid4

from packages.queue import InMemoryQueue, JobPayload, JobStatus, PlanGenerateJobV1


async def _record(seen: list[str], payload: JobPayload) -> None:
    assert isinstance(payload, PlanGenerateJobV1)
    seen.append(str(payload.session_id))


async def test_memory_queue_records_and_drains():
    q = InMemoryQueue()
    sid = uuid4()
    handle = await q.enqueue(PlanGenerateJobV1(session_id=sid))
    assert handle.queue == "plan.generate"
    assert q.enqueued == [PlanGenerateJobV1(session_id=sid)]
    seen: list[str] = []
    await q.drain({"plan.generate": lambda p: _record(seen, p)})
    assert seen == [str(sid)]
    assert q.enqueued == []


async def test_status_tracks_lifecycle():
    q = InMemoryQueue()
    handle = await q.enqueue(PlanGenerateJobV1(session_id=uuid4()))
    assert await q.status(handle.job_id) == JobStatus.queued
    assert await q.status("unknown") is None
    await q.drain({"plan.generate": lambda p: _record([], p)})
    assert await q.status(handle.job_id) == JobStatus.done


async def test_drain_without_handler_leaves_nothing_and_marks_failed():
    q = InMemoryQueue()
    handle = await q.enqueue(PlanGenerateJobV1(session_id=uuid4()))
    await q.drain({})
    assert q.enqueued == []
    assert await q.status(handle.job_id) == JobStatus.failed
