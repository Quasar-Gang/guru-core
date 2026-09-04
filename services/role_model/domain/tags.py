"""Tag vocabulary loading and validation (PRD 12.3).

Tags are the only classification mechanism for role models. Every tag is
``namespace:value``; the namespace whitelist and the value rules live in
``config/tag_vocab.yaml``.
"""

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from packages.config import CONFIG_DIR, load_yaml_config
from services.role_model.domain.errors import InvalidTag


class ValueRules(BaseModel):
    pattern: str
    max_length: int
    max_tags_per_record: int


class TagVocab(BaseModel):
    version: int
    mode: Literal["lenient", "strict"]
    namespaces: list[str]
    value_rules: ValueRules
    enum_only: dict[str, list[str]]
    known_values: dict[str, list[str]]
    required_tags: dict[str, list[str]]


def load_tag_vocab(path: Path | None = None) -> TagVocab:
    """Load the tag vocabulary, defaulting to ``config/tag_vocab.yaml``."""
    return load_yaml_config(path or CONFIG_DIR / "tag_vocab.yaml", TagVocab)


def parse_tag(tag: str) -> tuple[str, str]:
    """Split ``namespace:value``; raise :class:`InvalidTag` if malformed."""
    namespace, sep, value = tag.partition(":")
    if not sep or not namespace or not value:
        raise InvalidTag(f"tag must be 'namespace:value', got {tag!r}")
    return namespace, value


def validate_tags(tags: Sequence[str], kind: str, vocab: TagVocab) -> None:
    """Validate a record's tags against the vocabulary. Raise on the first problem."""
    if len(tags) > vocab.value_rules.max_tags_per_record:
        raise InvalidTag(f"too many tags: {len(tags)} > {vocab.value_rules.max_tags_per_record}")

    pattern = re.compile(vocab.value_rules.pattern)
    seen: set[str] = set()
    for tag in tags:
        namespace, value = parse_tag(tag)
        if namespace not in vocab.namespaces:
            raise InvalidTag(f"unknown namespace {namespace!r} in tag {tag!r}")
        if len(value) > vocab.value_rules.max_length:
            raise InvalidTag(
                f"value too long in tag {tag!r}: {len(value)} > {vocab.value_rules.max_length}"
            )
        if not pattern.fullmatch(value):
            raise InvalidTag(f"value does not match {vocab.value_rules.pattern!r}: {tag!r}")
        allowed = vocab.enum_only.get(namespace)
        if allowed is not None and value not in allowed:
            raise InvalidTag(f"namespace {namespace!r} only allows {allowed}, got {tag!r}")
        if (
            vocab.mode == "strict"
            and allowed is None
            and value not in vocab.known_values.get(namespace, [])
        ):
            raise InvalidTag(f"strict mode: unknown value in tag {tag!r}")
        seen.add(namespace)

    for namespace in vocab.required_tags.get(kind, []):
        if namespace not in seen:
            raise InvalidTag(f"{kind} requires at least one {namespace}: tag")


def learn_values(tags: Sequence[str], vocab: TagVocab) -> TagVocab:
    """Return a new vocab with previously unseen values appended to ``known_values``.

    Enum-only namespaces are never extended; the original vocab is left untouched.
    """
    known = {namespace: list(values) for namespace, values in vocab.known_values.items()}
    for tag in tags:
        namespace, value = parse_tag(tag)
        if namespace in vocab.enum_only:
            continue
        bucket = known.setdefault(namespace, [])
        if value not in bucket:
            bucket.append(value)
    return vocab.model_copy(update={"known_values": known})
