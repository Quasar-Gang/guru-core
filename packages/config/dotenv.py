"""Load `.env` into the process environment, without overriding what is already set.

Two things read configuration, and until this existed they disagreed about `.env`:
`pydantic-settings` reads the file directly, while the `${VAR:-default}` expansion in
`config/*.yaml` reads `os.environ`. So a developer who set `LLM_API_KEY` in `.env` got a
service that authenticated correctly and still answered from fixtures — no error, just the
wrong provider.

Existing environment variables always win, so a container's real environment is never
shadowed by a file that happened to be copied into the image.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

__all__ = ["load_dotenv"]

_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def load_dotenv(path: Path | str = ".env") -> list[str]:
    """Set any variable the file declares that the environment does not. Returns the names.

    Missing file is not an error: production sets real environment variables and has no
    `.env` at all.
    """
    file = Path(path)
    if not file.is_file():
        return []

    applied: list[str] = []
    for line in file.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _LINE.match(line)
        if match is None:
            continue
        name, raw = match.group(1), match.group(2)
        if name in os.environ:
            continue
        os.environ[name] = _unquote(raw)
        applied.append(name)
    return applied


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value
