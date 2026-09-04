"""build_llm: pick the implementation matching the configured adapter."""

from pathlib import Path
from typing import Any

import pytest

from packages.llm.anthropic_llm import AnthropicLLM
from packages.llm.config import LLMConfig, ProviderConfig, PurposeParams, RetryConfig
from packages.llm.factory import build_llm
from packages.llm.fake import FakeLLM
from packages.llm.openai_compat import OpenAICompatLLM
from packages.llm.ports import LLMError, Purpose
from packages.llm.prompts import PromptRegistry

PROMPTS_DIR = Path(__file__).resolve().parents[4] / "packages" / "llm" / "prompts"


class _FakeObserver:
    async def record(self, log: Any) -> None:
        return None


def _cfg(adapter: str) -> LLMConfig:
    return LLMConfig(
        provider=ProviderConfig(
            adapter=adapter,  # type: ignore[arg-type]
            base_url="http://llm.test/v1",
            api_key="k",
            model="m",
            structured_output="guided_json",
        ),
        params={
            Purpose.evaluate: PurposeParams(temperature=0.2, max_output_tokens=1500),
            Purpose.generate: PurposeParams(temperature=0.4, max_output_tokens=4000),
            Purpose.revise: PurposeParams(temperature=0.3, max_output_tokens=3000),
            Purpose.recommend: PurposeParams(temperature=0.3, max_output_tokens=800),
        },
        budgets={
            Purpose.evaluate: 100,
            Purpose.generate: 300,
            Purpose.revise: 200,
            Purpose.recommend: 600,
        },
        retry=RetryConfig(),
    )


def test_build_llm_selects_adapter_by_config(tmp_path: Path) -> None:
    prompts = PromptRegistry(PROMPTS_DIR)
    observer = _FakeObserver()

    assert isinstance(build_llm(_cfg("fake"), prompts, observer, fixtures_dir=tmp_path), FakeLLM)
    assert isinstance(build_llm(_cfg("openai_compat"), prompts, observer), OpenAICompatLLM)
    assert isinstance(build_llm(_cfg("anthropic"), prompts, observer), AnthropicLLM)


def test_build_llm_fake_without_fixtures_dir_raises() -> None:
    with pytest.raises(LLMError):
        build_llm(_cfg("fake"), PromptRegistry(PROMPTS_DIR), _FakeObserver())
