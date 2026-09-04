"""FakeLLM — LLMPort implementation for development and tests, answering from fixtures."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from packages.llm.ports import LLMError, LLMSchemaError, OutputT, Purpose

__all__ = ["FakeLLM"]


class FakeLLM:
    """Return a canned response per prompt name; `overrides` wins over `fixtures_dir`."""

    def __init__(
        self,
        fixtures_dir: Path,
        overrides: Mapping[str, Any] | None = None,
    ) -> None:
        self._fixtures_dir = fixtures_dir
        self._overrides = dict(overrides or {})
        self.calls: list[tuple[str, Purpose, dict[str, Any]]] = []

    async def complete(
        self,
        prompt_name: str,
        context: dict[str, Any],
        output_schema: type[OutputT],
        purpose: Purpose,
    ) -> OutputT:
        self.calls.append((prompt_name, purpose, context))
        payload = self._payload(prompt_name)
        try:
            return output_schema.model_validate(payload)
        except Exception as exc:  # noqa: BLE001 - normalise to the port's error type
            raise LLMSchemaError(
                f"fixture for {prompt_name!r} does not match schema: {exc}"
            ) from exc

    def _payload(self, prompt_name: str) -> Any:
        if prompt_name in self._overrides:
            return self._overrides[prompt_name]
        path = self._fixtures_dir / f"{prompt_name}.json"
        if not path.is_file():
            raise LLMError(f"no fixture for {prompt_name!r} in {self._fixtures_dir}")
        return json.loads(path.read_text(encoding="utf-8"))
