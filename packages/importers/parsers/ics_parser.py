"""ICS parser：每個 VEVENT 一個 DocEvent。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from icalendar import Calendar

from packages.importers.document import DocEvent, Document
from packages.importers.ports import RawBlob


def _to_utc(value: object) -> tuple[datetime, bool] | None:
    """回 (UTC aware datetime, 是否為全天)。無法辨識時回 None。"""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC), False
        return value.astimezone(UTC), False
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC), True
    return None


class IcsParser:
    """解析 iCalendar，DTSTART;VALUE=DATE 視為全天事件。"""

    def supports(self, fmt: str) -> bool:
        return fmt == "ics"

    def parse(self, blob: RawBlob) -> Document:
        if not blob.data.strip():
            return Document()

        calendar = Calendar.from_ical(blob.data)
        events: list[DocEvent] = []
        for component in calendar.walk("VEVENT"):
            start = _to_utc(_prop(component, "DTSTART"))
            if start is None:
                continue
            start_at, all_day = start
            end = _to_utc(_prop(component, "DTEND"))
            if end is not None:
                end_at = end[0]
            else:
                end_at = start_at + timedelta(days=1) if all_day else start_at
            events.append(
                DocEvent(
                    title=_text(component, "SUMMARY"),
                    start_at=start_at,
                    end_at=end_at,
                    all_day=all_day,
                    location=_text(component, "LOCATION") or None,
                    source_ref=_text(component, "UID") or None,
                )
            )
        return Document(events=events)


def _prop(component: object, key: str) -> object:
    value = component.get(key)  # type: ignore[attr-defined]  # icalendar 未提供型別資訊
    return getattr(value, "dt", None) if value is not None else None


def _text(component: object, key: str) -> str:
    value = component.get(key)  # type: ignore[attr-defined]  # icalendar 未提供型別資訊
    return "" if value is None else str(value).strip()
