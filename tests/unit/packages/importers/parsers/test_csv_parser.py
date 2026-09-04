from datetime import UTC, datetime

from packages.importers import RawBlob
from packages.importers.parsers import CsvParser

from . import load_blob as _blob


def test_csv_row_with_date_becomes_event():
    blob = RawBlob(
        data=b"title,start,end\nGym,2026-09-08T19:00:00Z,2026-09-08T20:00:00Z\n",
        content_type="text/csv",
        filename="a.csv",
    )
    doc = CsvParser().parse(blob)
    assert len(doc.events) == 1
    assert doc.events[0].title == "Gym"
    assert doc.events[0].start_at == datetime(2026, 9, 8, 19, tzinfo=UTC)
    assert doc.text_chunks == []


def test_csv_row_without_date_becomes_text_chunk():
    blob = RawBlob(data=b"name,note\nrun,easy pace\n", content_type="text/csv", filename="a.csv")
    doc = CsvParser().parse(blob)
    assert doc.events == []
    assert "easy pace" in doc.text_chunks[0].text


def test_csv_fixture_parses_two_events():
    doc = CsvParser().parse(_blob("sample.csv"))
    assert len(doc.events) == 2
    assert doc.events[0].title == "晨跑"
    assert doc.events[0].start_at == datetime(2026, 9, 8, 7, 0, tzinfo=UTC)
    assert doc.events[0].end_at == datetime(2026, 9, 8, 7, 40, tzinfo=UTC)
    assert doc.text_chunks == []


def test_csv_fixture_without_date_becomes_text_chunks():
    doc = CsvParser().parse(_blob("sample_no_date.csv"))
    assert doc.events == []
    assert [c.order for c in doc.text_chunks] == [0, 1]
    assert "upper body" in doc.text_chunks[1].text


def test_csv_empty_file_returns_empty_document():
    doc = CsvParser().parse(_blob("empty.csv"))
    assert doc.events == []
    assert doc.text_chunks == []


def test_csv_all_datetimes_are_utc_aware():
    doc = CsvParser().parse(_blob("sample.csv"))
    for event in doc.events:
        assert event.start_at.tzinfo is not None
        assert event.start_at.utcoffset() == datetime(2026, 1, 1, tzinfo=UTC).utcoffset()


def test_csv_supports_only_csv():
    parser = CsvParser()
    assert parser.supports("csv")
    assert not parser.supports("xlsx")
    assert not parser.supports("md")
