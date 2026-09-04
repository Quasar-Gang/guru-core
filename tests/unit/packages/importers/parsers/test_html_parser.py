from packages.importers import RawBlob
from packages.importers.parsers import HtmlParser

from . import load_blob as _blob


def test_html_splits_by_heading_and_strips_tags():
    doc = HtmlParser().parse(_blob("sample.html"))
    assert doc.events == []
    assert [c.section for c in doc.text_chunks] == ["訓練筆記", "現況"]
    assert "每週能跑三次。" in doc.text_chunks[1].text
    assert "<p>" not in doc.text_chunks[0].text


def test_html_empty_file_returns_empty_document():
    blob = RawBlob(data=b"", content_type="text/html", filename="empty.html")
    doc = HtmlParser().parse(blob)
    assert doc.events == []
    assert doc.text_chunks == []


def test_html_supports_only_html():
    parser = HtmlParser()
    assert parser.supports("html")
    assert not parser.supports("md")
