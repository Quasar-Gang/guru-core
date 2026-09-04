from pathlib import Path

import pytest
from pydantic import BaseModel

from packages.llm import FakeLLM, LLMError, Purpose


class ReadinessOutput(BaseModel):
    ready: bool
    missing: list[str] = []
    questions: list[dict] = []


async def test_fake_llm_returns_fixture(tmp_path: Path):
    (tmp_path / "evaluate_readiness.json").write_text(
        '{"ready": true, "missing": [], "questions": []}'
    )
    llm = FakeLLM(tmp_path)
    out = await llm.complete("evaluate_readiness", {"goal": "x"}, ReadinessOutput, Purpose.evaluate)
    assert out.ready is True
    assert llm.calls[0][0] == "evaluate_readiness"
    assert llm.calls[0][1] == Purpose.evaluate
    assert llm.calls[0][2] == {"goal": "x"}


async def test_fake_llm_override_wins(tmp_path: Path):
    (tmp_path / "evaluate_readiness.json").write_text('{"ready": true}')
    llm = FakeLLM(tmp_path, overrides={"evaluate_readiness": {"ready": False, "missing": ["when"]}})
    out = await llm.complete("evaluate_readiness", {}, ReadinessOutput, Purpose.evaluate)
    assert out.ready is False
    assert out.missing == ["when"]


async def test_fake_llm_missing_fixture_raises(tmp_path: Path):
    with pytest.raises(LLMError, match="no fixture"):
        await FakeLLM(tmp_path).complete("nope", {}, ReadinessOutput, Purpose.evaluate)


async def test_numbered_fixture_answers_the_nth_call(tmp_path):
    """A scripted conversation needs a different answer per round."""
    (tmp_path / "evaluate.json").write_text('{"ready": false, "missing": ["capacity"]}')
    (tmp_path / "evaluate.2.json").write_text('{"ready": true, "missing": []}')
    llm = FakeLLM(tmp_path)
    first = await llm.complete("evaluate", {}, ReadinessOutput, Purpose.evaluate)
    second = await llm.complete("evaluate", {}, ReadinessOutput, Purpose.evaluate)
    third = await llm.complete("evaluate", {}, ReadinessOutput, Purpose.evaluate)
    assert first.ready is False
    assert second.ready is True
    assert third.ready is False  # no .3.json, so it falls back to the base fixture


async def test_call_counts_are_per_prompt(tmp_path):
    (tmp_path / "a.json").write_text('{"ready": false, "missing": []}')
    (tmp_path / "b.json").write_text('{"ready": true, "missing": []}')
    (tmp_path / "b.2.json").write_text('{"ready": false, "missing": ["x"]}')
    llm = FakeLLM(tmp_path)
    await llm.complete("a", {}, ReadinessOutput, Purpose.evaluate)
    first_b = await llm.complete("b", {}, ReadinessOutput, Purpose.evaluate)
    assert first_b.ready is True  # b's own counter is at 1, unaffected by the call to a


async def test_overrides_win_over_numbered_fixtures(tmp_path):
    (tmp_path / "evaluate.2.json").write_text('{"ready": true, "missing": []}')
    llm = FakeLLM(tmp_path, overrides={"evaluate": {"ready": False, "missing": ["always"]}})
    await llm.complete("evaluate", {}, ReadinessOutput, Purpose.evaluate)
    second = await llm.complete("evaluate", {}, ReadinessOutput, Purpose.evaluate)
    assert second.missing == ["always"]
