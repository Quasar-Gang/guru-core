"""`.env` has to mean the same thing to pydantic-settings and to the YAML expansion.

The bug this prevents is silent: a developer sets `LLM_API_KEY` in `.env`, the settings
class picks it up, `config/llm.yaml` does not, and the service answers from fixtures with no
error at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from packages.config import load_dotenv


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SAMPLE_ONE", "SAMPLE_TWO", "SAMPLE_SET"):
        monkeypatch.delenv(name, raising=False)


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(body, encoding="utf-8")
    return path


def test_it_sets_what_the_file_declares(tmp_path: Path) -> None:
    import os

    load_dotenv(write(tmp_path, "SAMPLE_ONE=first\nSAMPLE_TWO=second\n"))
    assert os.environ["SAMPLE_ONE"] == "first"
    assert os.environ["SAMPLE_TWO"] == "second"


def test_a_real_environment_variable_always_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A container's own environment must never be shadowed by a file in the image."""
    import os

    monkeypatch.setenv("SAMPLE_SET", "from-the-environment")
    applied = load_dotenv(write(tmp_path, "SAMPLE_SET=from-the-file\n"))
    assert os.environ["SAMPLE_SET"] == "from-the-environment"
    assert "SAMPLE_SET" not in applied


def test_comments_blank_lines_and_export_prefixes(tmp_path: Path) -> None:
    import os

    body = "# a comment\n\n  export SAMPLE_ONE=first  \nnot a declaration\n"
    assert load_dotenv(write(tmp_path, body)) == ["SAMPLE_ONE"]
    assert os.environ["SAMPLE_ONE"] == "first"


@pytest.mark.parametrize(
    "line,expected",
    [
        ('SAMPLE_ONE="quoted"', "quoted"),
        ("SAMPLE_ONE='quoted'", "quoted"),
        ("SAMPLE_ONE=un quoted", "un quoted"),
        ("SAMPLE_ONE=", ""),
        ("SAMPLE_ONE=key=with=equals", "key=with=equals"),
    ],
)
def test_value_parsing(tmp_path: Path, line: str, expected: str) -> None:
    import os

    load_dotenv(write(tmp_path, line + "\n"))
    assert os.environ["SAMPLE_ONE"] == expected


def test_a_missing_file_is_not_an_error(tmp_path: Path) -> None:
    """Production sets real environment variables and ships no `.env` at all."""
    assert load_dotenv(tmp_path / "nothing-here") == []
