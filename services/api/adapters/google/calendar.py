"""CalendarPort implementations: `GoogleCalendar` for production, `FakeCalendar` for tests."""

from datetime import UTC, date, datetime, time
from typing import Any
from urllib.parse import quote

import httpx

from services.api.application.ports import CalendarEvent, CalendarEventWrite
from services.api.domain.errors import DomainError

__all__ = ["CALENDAR_API_BASE", "PRIMARY_CALENDAR_ID", "FakeCalendar", "GoogleCalendar"]

CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"
PRIMARY_CALENDAR_ID = "primary"
NO_TITLE = "(no title)"

#: Google answers a delete with 410 when the resource is already gone; both mean "done".
_DELETE_OK = (httpx.codes.OK, httpx.codes.NO_CONTENT, httpx.codes.NOT_FOUND, httpx.codes.GONE)


def _read_boundary(value: dict[str, Any]) -> tuple[datetime, bool]:
    """A Google event boundary is either `dateTime` (timed) or `date` (all-day)."""
    raw = value.get("dateTime")
    if isinstance(raw, str):
        parsed = datetime.fromisoformat(raw)
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)), False
    raw = value.get("date")
    if isinstance(raw, str):
        return datetime.combine(date.fromisoformat(raw), time.min, tzinfo=UTC), True
    raise DomainError("google calendar event has no start or end")


def _to_event(item: dict[str, Any]) -> CalendarEvent:
    start_at, all_day = _read_boundary(item.get("start") or {})
    end_at, _ = _read_boundary(item.get("end") or {})
    summary = item.get("summary")
    return CalendarEvent(
        external_id=str(item.get("id", "")),
        summary=summary if isinstance(summary, str) and summary else NO_TITLE,
        start_at=start_at,
        end_at=end_at,
        all_day=all_day,
    )


def _to_body(event: CalendarEventWrite) -> dict[str, Any]:
    if event.all_day:
        when = {
            "start": {"date": event.start_at.date().isoformat()},
            "end": {"date": event.end_at.date().isoformat()},
        }
    else:
        when = {
            "start": {"dateTime": event.start_at.isoformat()},
            "end": {"dateTime": event.end_at.isoformat()},
        }
    body: dict[str, Any] = {"summary": event.summary, "description": event.description, **when}
    if event.color_id is not None:
        body["colorId"] = event.color_id
    if event.private_props:
        body["extendedProperties"] = {"private": dict(event.private_props)}
    return body


class GoogleCalendar:
    """Google Calendar API v3 over HTTPS. The caller supplies an already-fresh access token."""

    #: Google's own per-page ceiling for `events.list`.
    PAGE_SIZE = 2500

    def __init__(
        self, client: httpx.AsyncClient | None = None, timeout_seconds: float = 20.0
    ) -> None:
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def list_events(
        self, access_token: str, time_min: datetime, time_max: datetime
    ) -> list[CalendarEvent]:
        events: list[CalendarEvent] = []
        params: dict[str, str] = {
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            # Expand recurring events so every occurrence carries its own concrete time range.
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": str(self.PAGE_SIZE),
        }
        while True:
            body = await self._json(
                "GET",
                f"{CALENDAR_API_BASE}/calendars/{PRIMARY_CALENDAR_ID}/events",
                access_token,
                params=params,
            )
            items = body.get("items")
            if isinstance(items, list):
                events.extend(_to_event(i) for i in items if isinstance(i, dict))
            page_token = body.get("nextPageToken")
            if not isinstance(page_token, str) or not page_token:
                return events
            params = {**params, "pageToken": page_token}

    async def create_calendar(self, access_token: str, summary: str) -> str:
        body = await self._json(
            "POST", f"{CALENDAR_API_BASE}/calendars", access_token, json={"summary": summary}
        )
        return self._read_id(body)

    async def create_event(
        self, access_token: str, calendar_id: str, event: CalendarEventWrite
    ) -> str:
        body = await self._json(
            "POST", self._events_url(calendar_id), access_token, json=_to_body(event)
        )
        return self._read_id(body)

    async def update_event(
        self, access_token: str, calendar_id: str, event_id: str, event: CalendarEventWrite
    ) -> None:
        await self._json(
            "PUT",
            f"{self._events_url(calendar_id)}/{quote(event_id, safe='')}",
            access_token,
            json=_to_body(event),
        )

    async def delete_event(self, access_token: str, calendar_id: str, event_id: str) -> None:
        await self._delete(
            f"{self._events_url(calendar_id)}/{quote(event_id, safe='')}", access_token
        )

    async def delete_calendar(self, access_token: str, calendar_id: str) -> None:
        await self._delete(
            f"{CALENDAR_API_BASE}/calendars/{quote(calendar_id, safe='')}", access_token
        )

    @staticmethod
    def _events_url(calendar_id: str) -> str:
        return f"{CALENDAR_API_BASE}/calendars/{quote(calendar_id, safe='')}/events"

    @staticmethod
    def _read_id(body: dict[str, Any]) -> str:
        value = body.get("id")
        if not isinstance(value, str) or not value:
            raise DomainError("google calendar response has no id")
        return value

    async def _delete(self, url: str, access_token: str) -> None:
        response = await self._request("DELETE", url, access_token)
        if response.status_code not in _DELETE_OK:
            raise DomainError(f"google calendar call failed: {response.status_code}")

    async def _json(
        self,
        method: str,
        url: str,
        access_token: str,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = await self._request(method, url, access_token, params=params, json=json)
        if response.status_code != httpx.codes.OK:
            raise DomainError(f"google calendar call failed: {response.status_code}")
        body = response.json() if response.content else {}
        return body if isinstance(body, dict) else {}

    async def _request(
        self,
        method: str,
        url: str,
        access_token: str,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {access_token}"}
        if self._client is not None:
            return await self._client.request(
                method, url, headers=headers, params=params, json=json
            )
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            return await client.request(method, url, headers=headers, params=params, json=json)


class FakeCalendar:
    """Test double: returns a fixed event list and records every write it was asked to make."""

    def __init__(
        self,
        events: list[CalendarEvent] | None = None,
        delete_calendar_raises: Exception | None = None,
    ) -> None:
        self.events = list(events or [])
        self.delete_calendar_raises = delete_calendar_raises
        self.listed: list[tuple[str, datetime, datetime]] = []
        self.created_calendars: list[str] = []
        self.created_events: list[tuple[str, CalendarEventWrite]] = []
        self.updated_events: list[tuple[str, str, CalendarEventWrite]] = []
        self.deleted_events: list[tuple[str, str]] = []
        self.deleted_calendars: list[str] = []
        self._next_id = 0

    async def list_events(
        self, access_token: str, time_min: datetime, time_max: datetime
    ) -> list[CalendarEvent]:
        self.listed.append((access_token, time_min, time_max))
        return list(self.events)

    async def create_calendar(self, access_token: str, summary: str) -> str:
        self.created_calendars.append(summary)
        return f"fake-calendar-{len(self.created_calendars)}"

    async def create_event(
        self, access_token: str, calendar_id: str, event: CalendarEventWrite
    ) -> str:
        self.created_events.append((calendar_id, event))
        self._next_id += 1
        return f"fake-event-{self._next_id}"

    async def update_event(
        self, access_token: str, calendar_id: str, event_id: str, event: CalendarEventWrite
    ) -> None:
        self.updated_events.append((calendar_id, event_id, event))

    async def delete_event(self, access_token: str, calendar_id: str, event_id: str) -> None:
        self.deleted_events.append((calendar_id, event_id))

    async def delete_calendar(self, access_token: str, calendar_id: str) -> None:
        if self.delete_calendar_raises is not None:
            raise self.delete_calendar_raises
        self.deleted_calendars.append(calendar_id)
