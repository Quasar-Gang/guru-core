"""Expand ``${VAR}`` / ``${VAR:-default}`` placeholders in raw config text."""

import os
import re
from collections.abc import Mapping

__all__ = ["MissingEnvVar", "expand_env"]

_PATTERN = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")


class MissingEnvVar(RuntimeError):
    """Raised when a referenced env var is absent and has no default."""


def expand_env(raw: str, environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ

    def replace(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        value = env.get(name)
        if value is not None:
            return value
        if default is not None:
            return default
        raise MissingEnvVar(f"missing environment variable: {name}")

    return _PATTERN.sub(replace, raw)
