"""CSV parser：有時間欄位的列進 events，其餘整列進 text_chunks。"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from datetime import UTC, datetime

from packages.importers.document import DocEvent, Document, TextChunk
from packages.importers.ports import RawBlob

_START_KEYWORDS = ("start", "開始", "date", "日期")
_END_KEYWORDS = ("end", "結束")

_DATE_FORMATS = ("%Y/%m/%d %H:%M", "%Y/%m/%d", "%Y%m%d")


def is_time_header(header: str) -> bool:
    """表頭是否代表時間欄位（開始或結束）。"""
    lowered = header.strip().lower()
    return any(keyword in lowered for keyword in (*_START_KEYWORDS, *_END_KEYWORDS))


def _is_start_header(header: str) -> bool:
    lowered = header.strip().lower()
    return any(keyword in lowered for keyword in _START_KEYWORDS)


def _is_end_header(header: str) -> bool:
    lowered = header.strip().lower()
    return any(keyword in lowered for keyword in _END_KEYWORDS)


def parse_datetime(value: object) -> datetime | None:
    """把儲存格內容轉成 UTC aware datetime；轉不出來回 None。"""
    if isinstance(value, datetime):
        return _as_utc(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return _as_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return _as_utc(datetime.strptime(text, fmt))
        except ValueError:
            continue
    return None


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)


def rows_to_document(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> Document:
    """把表頭 + 資料列轉成 Document（CSV 與 XLSX 共用）。"""
    events: list[DocEvent] = []
    chunks: list[TextChunk] = []
    for row in rows:
        cells = [_as_text(cell) for cell in row]
        if not any(cell for cell in cells):
            continue
        pairs = list(zip(headers, row, strict=False))
        event = _row_to_event(pairs)
        if event is not None:
            events.append(event)
            continue
        text = "\n".join(
            f"{header}: {_as_text(value)}" for header, value in pairs if _as_text(value)
        )
        if text:
            chunks.append(TextChunk(text=text, order=len(chunks)))
    return Document(events=events, text_chunks=chunks)


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value).strip()


def _row_to_event(pairs: Sequence[tuple[str, object]]) -> DocEvent | None:
    start_at: datetime | None = None
    end_at: datetime | None = None
    for header, value in pairs:
        parsed = parse_datetime(value)
        if parsed is None:
            continue
        if start_at is None and _is_start_header(header):
            start_at = parsed
        elif end_at is None and _is_end_header(header):
            end_at = parsed
    if start_at is None:
        return None
    titles = (_as_text(value) for header, value in pairs if not is_time_header(header))
    title = next((text for text in titles if text), "")
    return DocEvent(title=title, start_at=start_at, end_at=end_at or start_at)


class CsvParser:
    """解析 CSV（UTF-8，允許 BOM）。"""

    def supports(self, fmt: str) -> bool:
        return fmt == "csv"

    def parse(self, blob: RawBlob) -> Document:
        text = blob.data.decode("utf-8-sig", errors="replace")
        if not text.strip():
            return Document()
        reader = csv.reader(io.StringIO(text))
        try:
            headers = next(reader)
        except StopIteration:
            return Document()
        return rows_to_document(headers, [list(row) for row in reader])
