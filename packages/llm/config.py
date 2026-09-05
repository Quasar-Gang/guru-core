"""Pydantic models and loader for `config/llm.yaml`."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, field_validator

from packages.config import CONFIG_DIR, load_yaml_config
from packages.llm.ports import Purpose

__all__ = [
    "LLMConfig",
    "ProviderConfig",
    "PurposeParams",
    "RetryConfig",
    "load_llm_config",
]


class ProviderConfig(BaseModel):
    adapter: Literal["openai_compat", "anthropic", "fake"]
    base_url: str | None = None
    api_key: str = "dummy"
    model: str = ""
    structured_output: Literal["guided_json", "json_schema", "tool_use", "prompt"]
    max_context_tokens: int = 16000
    timeout_seconds: int = 180

    #: In-process cap on simultaneous requests to this provider. A local runtime holds
    #: one set of weights and one KV cache, so two concurrent generations compete for
    #: the same unified memory; 1 keeps a laptop demo predictable. 0 means no cap,
    #: which is what a hosted provider wants. The limit is per process, so N workers
    #: still make N requests — that is deliberate, since the queue is where
    #: cross-process backpressure belongs.
    concurrency: int = 0

    @field_validator("base_url", mode="before")
    @classmethod
    def _blank_base_url_is_none(cls, value: object) -> object:
        return None if value == "" else value


class PurposeParams(BaseModel):
    temperature: float
    max_output_tokens: int

    #: Sent only when set, because the accepted values are provider-specific: Ollama
    #: and gpt-oss read "none"/"low"/"medium"/"high", Anthropic has no such field at
    #: all. Leave it unset — or set the env var to empty — and no adapter sends it,
    #: so switching to a cloud provider needs no edit here.
    reasoning_effort: str | None = None

    @field_validator("reasoning_effort", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        """An env var expanded to an empty string means "do not send it"."""
        return None if value == "" else value


class RetryConfig(BaseModel):
    max_attempts: int = 3


class LLMConfig(BaseModel):
    provider: ProviderConfig
    params: dict[Purpose, PurposeParams]
    budgets: dict[Purpose, int]
    retry: RetryConfig

    def params_for(self, purpose: Purpose) -> PurposeParams:
        return self.params[purpose]

    def budget_for(self, purpose: Purpose) -> int:
        return self.budgets[purpose]


def load_llm_config(path: Path | None = None) -> LLMConfig:
    return load_yaml_config(path or CONFIG_DIR / "llm.yaml", LLMConfig)
