"""The codebase is English-only, and that is checked rather than trusted.

Localisation belongs to the client. A backend that hard-codes one language into its prompts,
its seeds or its error messages has quietly decided who the product is for, and the decision
is invisible until someone outside that audience arrives.

The one exception is deliberate: `tests/fixtures/importers/sample.*` simulates user uploads
and is non-ASCII on purpose, so encoding bugs surface in the parser suite.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

#: CJK ideographs, kana and Hangul. Written as escapes so this file passes its own check.
_NON_LATIN = re.compile("[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")

_SCANNED = ("*.py", "*.md", "*.yaml", "*.yml", "*.toml", "*.sh", "*.json")

_SKIPPED_DIRS = {
    ".git",
    ".venv",
    ".data",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".import_linter_cache",
    "node_modules",
}

#: Two exemptions, and both are about *other people's* text rather than ours:
#: the upload fixtures simulate real user files, and the parsers recognise column headings
#: in whatever language the uploaded file was written in.
_EXEMPT = (
    ROOT / "tests" / "fixtures" / "importers",
    ROOT / "packages" / "importers" / "parsers",
)


def _files() -> list[Path]:
    found: list[Path] = []
    for pattern in _SCANNED:
        for path in ROOT.rglob(pattern):
            if any(part in _SKIPPED_DIRS for part in path.parts):
                continue
            if any(directory in path.parents for directory in _EXEMPT):
                continue
            found.append(path)
    return found


@pytest.mark.parametrize("path", _files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_non_latin_text_outside_the_upload_fixtures(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:  # a binary file that happens to match a glob
        return
    offenders = [
        f"line {number}: {line.strip()[:80]}"
        for number, line in enumerate(text.splitlines(), start=1)
        if _NON_LATIN.search(line)
    ]
    assert not offenders, f"{path.relative_to(ROOT)} is not English-only:\n" + "\n".join(offenders)
