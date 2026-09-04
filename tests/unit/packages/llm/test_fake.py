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
