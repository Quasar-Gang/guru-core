"""Pydantic models and loader for `config/llm.yaml`."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel

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


class PurposeParams(BaseModel):
    temperature: float
    max_output_tokens: int


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
