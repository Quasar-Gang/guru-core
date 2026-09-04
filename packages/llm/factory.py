"""build_llm — pick the LLMPort implementation named by the configuration."""

from pathlib import Path
from typing import TYPE_CHECKING

from packages.llm.anthropic_llm import AnthropicLLM
from packages.llm.config import LLMConfig
from packages.llm.fake import FakeLLM
from packages.llm.openai_compat import OpenAICompatLLM
from packages.llm.ports import LLMError, LLMPort
from packages.llm.prompts import PromptRegistry

if TYPE_CHECKING:
    from packages.llm.observability import LlmObserver

__all__ = ["build_llm"]


def build_llm(
    config: LLMConfig,
    prompts: PromptRegistry,
    observer: "LlmObserver",
    fixtures_dir: Path | None = None,
) -> LLMPort:
    adapter = config.provider.adapter
    if adapter == "fake":
        if fixtures_dir is None:
            raise LLMError("fake adapter requires fixtures_dir")
        # The fake reports its calls too, so running a service on LLM_ADAPTER=fake still
        # fills `llm_calls` and the observability wiring is exercised end to end.
        return FakeLLM(fixtures_dir, observer=observer)
    if adapter == "openai_compat":
        return OpenAICompatLLM(config, prompts, observer)
    return AnthropicLLM(config, prompts, observer)
