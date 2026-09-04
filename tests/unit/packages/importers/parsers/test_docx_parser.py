from packages.importers import RawBlob
from packages.importers.parsers import DocxParser

from . import load_blob as _blob


def test_docx_splits_at_headings():
    doc = DocxParser().parse(_blob("sample.docx"))
    assert doc.events == []
    assert [c.section for c in doc.text_chunks] == ["訓練筆記", "現況"]
    assert doc.text_chunks[0].text == "目前 5K 大約 38 分。"
    assert doc.text_chunks[1].text == "每週能跑三次。"


def test_docx_empty_document_returns_empty_document():
    from io import BytesIO

    from docx import Document as DocxDocument

    buf = BytesIO()
    DocxDocument().save(buf)
    blob = RawBlob(
        data=buf.getvalue(),
        content_type=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        filename="empty.docx",
    )
    doc = DocxParser().parse(blob)
    assert doc.events == []
    assert doc.text_chunks == []


def test_docx_supports_only_docx():
    parser = DocxParser()
    assert parser.supports("docx")
    assert not parser.supports("pdf")
