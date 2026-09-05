"""The Role Model tag vocabulary, loaded from `config/tag_vocab.yaml`.

Tags say which shelf a template sits on. They never decide fit — that is the Fit Verdict's
job, and it reasons from Reports rather than from labels. Keeping the vocabulary controlled
is what stops the catalogue drifting into a folksonomy nobody can filter on.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from packages.config import CONFIG_DIR, load_yaml_config
from services.catalog.domain.errors import InvalidTag

__all__ = ["TagVocabulary", "ValueRules", "load_tag_vocabulary"]


class ValueRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern: str = r"^[a-z0-9]+(-[a-z0-9]+)*$"
    max_length: int = Field(default=32, ge=1)
    max_tags_per_record: int = Field(default=8, ge=1)


class TagVocabulary(BaseModel):
    """`namespace:value`, where the namespace is closed and some values are too."""

    model_config = ConfigDict(extra="forbid")

    version: int = 2
    namespaces: list[str] = Field(min_length=1)
    value_rules: ValueRules = ValueRules()
    enum_only: dict[str, list[str]] = Field(default_factory=dict)
    known_values: dict[str, list[str]] = Field(default_factory=dict)

    def validate_tags(self, tags: list[str]) -> list[str]:
        """Return the tags, normalized and deduplicated, or raise `InvalidTag`."""
        if len(tags) > self.value_rules.max_tags_per_record:
            raise InvalidTag(
                f"at most {self.value_rules.max_tags_per_record} tags per role model, "
                f"got {len(tags)}"
            )
        pattern = re.compile(self.value_rules.pattern)
        seen: list[str] = []
        for raw in tags:
            namespace, separator, value = raw.strip().lower().partition(":")
            if not separator:
                raise InvalidTag(f"tag {raw!r} must be written as 'namespace:value'")
            if namespace not in self.namespaces:
                raise InvalidTag(
                    f"unknown tag namespace {namespace!r}; "
                    f"allowed: {', '.join(sorted(self.namespaces))}"
                )
            if len(value) > self.value_rules.max_length or not pattern.match(value):
                raise InvalidTag(f"tag value {value!r} does not match {self.value_rules.pattern}")
            allowed = self.enum_only.get(namespace)
            if allowed is not None and value not in allowed:
                raise InvalidTag(
                    f"namespace {namespace!r} is closed; allowed values: {', '.join(allowed)}"
                )
            tag = f"{namespace}:{value}"
            if tag not in seen:
                seen.append(tag)
        return seen


def load_tag_vocabulary(path: Path | None = None) -> TagVocabulary:
    return load_yaml_config(path or CONFIG_DIR / "tag_vocab.yaml", TagVocabulary)
