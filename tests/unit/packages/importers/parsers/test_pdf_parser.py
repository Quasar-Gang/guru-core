from packages.importers import RawBlob
from packages.importers.parsers import PdfParser

from . import load_blob as _blob


def test_pdf_makes_one_chunk_per_page():
    doc = PdfParser().parse(_blob("sample.pdf"))
    assert doc.events == []
    assert len(doc.text_chunks) == 2
    assert [c.section for c in doc.text_chunks] == ["page 1", "page 2"]
    assert [c.order for c in doc.text_chunks] == [0, 1]


def test_pdf_empty_file_returns_empty_document():
    blob = RawBlob(data=b"", content_type="application/pdf", filename="empty.pdf")
    doc = PdfParser().parse(blob)
    assert doc.events == []
    assert doc.text_chunks == []


def test_pdf_supports_only_pdf():
    parser = PdfParser()
    assert parser.supports("pdf")
    assert not parser.supports("docx")
