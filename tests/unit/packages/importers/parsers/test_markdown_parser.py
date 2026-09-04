from packages.importers.parsers import MarkdownParser

from . import load_blob as _blob


def test_markdown_splits_by_heading():
    doc = MarkdownParser().parse(_blob("sample.md"))
    assert doc.events == []
    sections = [c.section for c in doc.text_chunks]
    assert sections == ["訓練筆記", "現況", "限制"]
    assert "38 分" in doc.text_chunks[0].text
    assert [c.order for c in doc.text_chunks] == [0, 1, 2]


def test_markdown_empty_file_returns_empty_document():
    doc = MarkdownParser().parse(_blob("empty.md"))
    assert doc.events == []
    assert doc.text_chunks == []


def test_markdown_supports_only_md():
    parser = MarkdownParser()
    assert parser.supports("md")
    assert not parser.supports("html")
