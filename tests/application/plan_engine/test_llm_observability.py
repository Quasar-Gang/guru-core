"""Every LLM call made while evaluating a session lands a row in `llm_calls` (PRD 7.8)."""

from packages.logging import bind_job_id
from packages.queue.jobs import PlanGenerateJobV1
from services.plan_engine.container import build_test_container
from tests.application.plan_engine.helpers import seed_session


async def test_evaluate_session_records_every_llm_call() -> None:
    c = build_test_container()
    sid = await seed_session(c, goal="run 5k under 30 minutes in 12 weeks")

    await c.evaluate_session(PlanGenerateJobV1(session_id=sid))

    records = c.llm_calls.records  # type: ignore[attr-defined]  # InMemoryLlmCallRepo
    assert [r.prompt_name for r in records] == [name for name, _, _ in c.llm.calls]  # type: ignore[attr-defined]
    assert "evaluate_readiness" in {r.prompt_name for r in records}
    for record in records:
        assert record.purpose in {"evaluate", "generate"}
        assert record.attempts == 1
        assert record.degraded is False
        assert record.latency_ms >= 0


async def test_recorded_calls_carry_the_bound_job_id() -> None:
    c = build_test_container()
    sid = await seed_session(c)

    with bind_job_id(str(sid)):
        await c.evaluate_session(PlanGenerateJobV1(session_id=sid))

    records = c.llm_calls.records  # type: ignore[attr-defined]  # InMemoryLlmCallRepo
    assert records
    assert {r.job_id for r in records} == {str(sid)}
