"""Prompt template registry: load `.md` templates, split SYSTEM/USER, render with jinja2."""

import re
from pathlib import Path
from typing import Any

import yaml
from jinja2 import StrictUndefined, Template
from pydantic import BaseModel

from packages.llm.ports import LLMError

__all__ = ["PromptRegistry", "RenderedPrompt"]

_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
_SECTION = re.compile(r"^#[ \t]+(SYSTEM|USER)[ \t]*$", re.MULTILINE)


class RenderedPrompt(BaseModel):
    name: str
    version: str
    system: str
    user: str


class _Template(BaseModel):
    version: str
    system: str
    user: str


class PromptRegistry:
    """Load prompt templates from a directory, parsing and caching each on first use."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._cache: dict[str, _Template] = {}

    def render(self, name: str, context: dict[str, Any]) -> RenderedPrompt:
        tpl = self._load(name)
        return RenderedPrompt(
            name=name,
            version=tpl.version,
            system=_render(tpl.system, context),
            user=_render(tpl.user, context),
        )

    def version(self, name: str) -> str:
        return self._load(name).version

    def _load(self, name: str) -> _Template:
        cached = self._cache.get(name)
        if cached is not None:
            return cached
        path = self._directory / f"{name}.md"
        if not path.is_file():
            raise LLMError(f"no prompt template for {name!r} in {self._directory}")
        tpl = _parse(name, path.read_text(encoding="utf-8"))
        self._cache[name] = tpl
        return tpl


def _render(source: str, context: dict[str, Any]) -> str:
    template = Template(source, undefined=StrictUndefined, keep_trailing_newline=False)
    rendered: str = template.render(**context)
    return rendered


def _parse(name: str, raw: str) -> _Template:
    match = _FRONTMATTER.match(raw)
    if match is None:
        raise LLMError(f"prompt {name!r} is missing YAML frontmatter")
    meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta, dict) or "version" not in meta:
        raise LLMError(f"prompt {name!r} frontmatter has no version")
    sections = _split_sections(name, raw[match.end() :])
    return _Template(version=str(meta["version"]), system=sections["SYSTEM"], user=sections["USER"])


def _split_sections(name: str, body: str) -> dict[str, str]:
    parts = _SECTION.split(body)
    sections = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    missing = {"SYSTEM", "USER"} - sections.keys()
    if missing:
        raise LLMError(f"prompt {name!r} is missing section(s): {', '.join(sorted(missing))}")
    return sections
