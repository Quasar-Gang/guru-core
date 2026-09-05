"""Keep docs/db/schema.md honest.

A schema document rots the moment someone adds a table and forgets the docs, and
the rot is invisible until a reader trusts a stale page. These checks fail the
build instead.
"""

from pathlib import Path

import pytest

from packages.repo.models import Base

DOC = Path(__file__).resolve().parents[3] / "docs" / "db" / "schema.md"


@pytest.fixture(scope="module")
def doc() -> str:
    return DOC.read_text(encoding="utf-8")


def test_every_table_has_a_section(doc: str) -> None:
    missing = [name for name in Base.metadata.tables if f"### `{name}`" not in doc]
    assert not missing, f"tables missing from the schema doc: {missing}"


def test_no_section_describes_a_table_that_no_longer_exists(doc: str) -> None:
    import re

    documented = set(re.findall(r"### `(\w+)`", doc))
    stale = documented - set(Base.metadata.tables)
    assert not stale, f"schema doc describes tables that were dropped: {sorted(stale)}"


def test_every_column_is_listed(doc: str) -> None:
    """A new column is the most common thing to add and the easiest to forget."""
    missing: list[str] = []
    for table_name, table in Base.metadata.tables.items():
        section = doc.split(f"### `{table_name}`", 1)
        if len(section) < 2:
            continue
        # a section runs until the next "### " heading
        body = section[1].split("\n### ", 1)[0]
        missing += [f"{table_name}.{c.name}" for c in table.columns if f"`{c.name}`" not in body]
    assert not missing, f"columns missing from the schema doc: {missing}"


def test_no_placeholder_survived(doc: str) -> None:
    assert "INCLUDE_" not in doc
