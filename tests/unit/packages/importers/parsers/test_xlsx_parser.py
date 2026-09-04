from datetime import UTC, datetime

from packages.importers import RawBlob
from packages.importers.parsers import XlsxParser

from . import load_blob as _blob


def test_xlsx_rows_with_date_become_events():
    doc = XlsxParser().parse(_blob("sample.xlsx"))
    assert len(doc.events) == 2
    assert doc.events[0].title == "晨跑"
    assert doc.events[0].start_at == datetime(2026, 9, 8, 7, 0, tzinfo=UTC)
    assert doc.text_chunks == []


def test_xlsx_empty_workbook_returns_empty_document():
    from io import BytesIO

    from openpyxl import Workbook

    wb = Workbook()
    buf = BytesIO()
    wb.save(buf)
    blob = RawBlob(
        data=buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="empty.xlsx",
    )
    doc = XlsxParser().parse(blob)
    assert doc.events == []
    assert doc.text_chunks == []


def test_xlsx_supports_only_xlsx():
    parser = XlsxParser()
    assert parser.supports("xlsx")
    assert not parser.supports("csv")
