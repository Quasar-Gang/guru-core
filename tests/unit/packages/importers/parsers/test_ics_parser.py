from datetime import UTC, datetime

from packages.importers import RawBlob
from packages.importers.parsers import IcsParser

from . import load_blob as _blob


def test_ics_all_day_event():
    doc = IcsParser().parse(_blob("sample.ics"))
    e = next(e for e in doc.events if e.all_day)
    assert e.end_at > e.start_at


def test_ics_timed_event_is_utc_aware():
    doc = IcsParser().parse(_blob("sample.ics"))
    assert len(doc.events) == 2
    timed = next(e for e in doc.events if not e.all_day)
    assert timed.title == "週會"
    assert timed.start_at == datetime(2026, 9, 8, 9, 0, tzinfo=UTC)
    assert timed.end_at == datetime(2026, 9, 8, 10, 0, tzinfo=UTC)
    assert timed.location == "會議室 A"
    assert timed.source_ref == "evt-1@example.com"


def test_ics_naive_datetime_is_treated_as_utc():
    data = (
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//EN\r\n"
        b"BEGIN:VEVENT\r\nUID:n-1\r\nDTSTART:20260908T090000\r\n"
        b"DTEND:20260908T100000\r\nSUMMARY:naive\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    doc = IcsParser().parse(RawBlob(data=data, content_type="text/calendar", filename="n.ics"))
    assert doc.events[0].start_at == datetime(2026, 9, 8, 9, 0, tzinfo=UTC)


def test_ics_empty_file_returns_empty_document():
    blob = RawBlob(data=b"", content_type="text/calendar", filename="empty.ics")
    doc = IcsParser().parse(blob)
    assert doc.events == []
    assert doc.text_chunks == []


def test_ics_supports_only_ics():
    parser = IcsParser()
    assert parser.supports("ics")
    assert not parser.supports("csv")
