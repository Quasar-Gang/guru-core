import pytest

from packages.importers import default_registry

from .parsers import load_blob


@pytest.mark.parametrize(
    "name",
    [
        "sample.csv",
        "sample.xlsx",
        "sample.md",
        "sample.html",
        "sample.pdf",
        "sample.docx",
        "sample.ics",
    ],
)
def test_default_registry_parses_every_fixture(name):
    doc = default_registry().parse(load_blob(name))
    assert doc.events or doc.text_chunks


@pytest.mark.parametrize("name", ["empty.csv", "empty.md"])
def test_default_registry_returns_empty_document_for_empty_files(name):
    doc = default_registry().parse(load_blob(name))
    assert doc.events == []
    assert doc.text_chunks == []
