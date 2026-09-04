"""EvaluateSession: readiness evaluation and the follow-up loop (plan Task 22, PRD 3.1/3.4)."""

from typing import Any

import pytest

from packages.llm.fake import FakeLLM
from packages.llm.ports import LLMTransportError
from packages.queue.jobs import PlanContinueJobV1, PlanGenerateJobV1
from services.plan_engine.container import build_test_container
from tests.application.plan_engine.helpers import (
    FIXTURES_DIR,
    RaisingLLM,
    seed_answered_round,
    seed_session,
)


def _q(question_id: str, metric_id: str) -> dict[str, Any]:
    return {
        "id": question_id,
        "metric_id": metric_id,
        "text": "how much time can you commit each week?",
        "options": ["two evenings", "three evenings", "weekends only"],
        "allow_custom": True,
        "allow_skip": True,
    }


def _fake(payload: dict[str, Any]) -> FakeLLM:
    return FakeLLM(FIXTURES_DIR, overrides={"evaluate_readiness": payload})


async def test_ready_true_goes_straight_to_generating() -> None:
    c = build_test_container(
        llm=_fake({"ready": True, "missing": [], "questions": []}),
    )
    sid = await seed_session(c, goal="run 5k under 30 minutes in 12 weeks")

    await c.evaluate_session(PlanGenerateJobV1(session_id=sid))

    s = await c.sessions.get_unscoped(sid)
    assert s is not None
    assert s.status == "done"  # generate_plans already ran, synchronously
    assert len(await c.plans.list_for_session(sid)) == 3


async def test_not_ready_creates_followup_round_and_questions() -> None:
    c = build_test_container(
        llm=_fake({"ready": False, "missing": ["capacity"], "questions": [_q("q1", "capacity")]}),
    )
    sid = await seed_session(c)

    await c.evaluate_session(PlanGenerateJobV1(session_id=sid))

    s = await c.sessions.get_unscoped(sid)
    assert s is not None
    assert s.status == "questioning"
    assert s.round == 1
    r = await c.followups.latest(sid)
    assert r is not None
    assert r.round_no == 0
    assert len(r.questions) == 1


async def test_second_round_then_force_generate() -> None:
    # round has reached max_followup_rounds=2, so we generate even with ready=false
    c = build_test_container(
        llm=_fake({"ready": False, "missing": ["baseline"], "questions": [_q("q1", "baseline")]}),
    )
    sid = await seed_session(c, round=2)

    await c.evaluate_session(PlanContinueJobV1(session_id=sid))

    s = await c.sessions.get_unscoped(sid)
    assert s is not None
    assert s.status == "done"
    plan = (await c.plans.list_for_session(sid))[0]
    assert any("系統假設" in a or "假設" in a for a in plan.structure["assumptions"])


async def test_previous_answers_reach_the_prompt_context() -> None:
    llm = _fake({"ready": True, "missing": [], "questions": []})
    c = build_test_container(llm=llm)
    sid = await seed_session(c, status="questioning", round=1)
    await seed_answered_round(c, sid, metric_id="horizon", answer="12 weeks, no fixed deadline")

    await c.evaluate_session(PlanContinueJobV1(session_id=sid))

    evaluate_calls = [call for call in llm.calls if call[0] == "evaluate_readiness"]
    assert evaluate_calls
    context = evaluate_calls[-1][2]
    answers = context["previous_rounds"][0]["answers"]
    assert answers[0]["answer"] == "12 weeks, no fixed deadline"
    assert context["previous_rounds"][0]["round_no"] == 0


async def test_terminal_session_is_noop() -> None:
    llm = _fake({"ready": True, "missing": [], "questions": []})
    c = build_test_container(llm=llm)
    sid = await seed_session(c, status="done")

    await c.evaluate_session(PlanGenerateJobV1(session_id=sid))

    assert llm.calls == []
    assert await c.plans.list_for_session(sid) == []


async def test_llm_failure_marks_session_failed() -> None:
    c = build_test_container(llm=RaisingLLM(LLMTransportError("boom")))
    sid = await seed_session(c)

    with pytest.raises(LLMTransportError):
        await c.evaluate_session(PlanGenerateJobV1(session_id=sid))

    s = await c.sessions.get_unscoped(sid)
    assert s is not None
    assert s.status == "failed"
    assert s.error is not None and "boom" in s.error


async def test_status_is_mirrored_to_cache() -> None:
    c = build_test_container(
        llm=_fake({"ready": False, "missing": ["capacity"], "questions": [_q("q1", "capacity")]}),
    )
    sid = await seed_session(c)

    await c.evaluate_session(PlanGenerateJobV1(session_id=sid))

    assert await c.cache.get(f"session:{sid}:status") == "questioning"

    ready = build_test_container(llm=_fake({"ready": True, "missing": [], "questions": []}))
    ready_sid = await seed_session(ready)
    await ready.evaluate_session(PlanGenerateJobV1(session_id=ready_sid))
    assert await ready.cache.get(f"session:{ready_sid}:status") == "done"
