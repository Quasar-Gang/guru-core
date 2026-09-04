"""Google Calendar import: pull events with the connection's access token, store a Document."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest

from services.api.adapters.google.calendar import FakeCalendar, GoogleCalendar
from services.api.application.import_google_calendar import ImportGoogleCalendar
from services.api.application.ports import CalendarEvent, CalendarEventWrite
from services.api.container import ApiContainer, build_test_container
from services.api.domain.errors import DomainError, InvalidInput, ReauthRequired

NOW = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def _event(external_id: str = "ev-1") -> CalendarEvent:
    return CalendarEvent(
        external_id=external_id,
        summary="Standup",
        start_at=NOW,
        end_at=NOW + timedelta(minutes=30),
        all_day=False,
    )


async def _user(container: ApiContainer) -> UUID:
    user = await container.users.create("calendar@example.com", "calendar-sub")
    return user.id


# --- use case --------------------------------------------------------------------------


async def test_import_google_calendar_creates_document_with_events() -> None:
    calendar = FakeCalendar([_event()])
    container = build_test_container(calendar=calendar)
    user_id = await _user(container)
    await container.complete_integration(user_id, "google", "code")

    view = await container.import_google_calendar(user_id)

    assert view.status == "parsed"
    assert view.event_count == 1
    assert view.source == "google_calendar"
    assert view.format == "ics"

    document = await container.documents.get_by_import(view.id)
    assert document is not None
    assert document.events[0]["title"] == "Standup"
    assert document.events[0]["source_ref"] == "ev-1"


async def test_import_google_calendar_uses_the_default_window() -> None:
    calendar = FakeCalendar([])
    container = build_test_container(calendar=calendar)
    user_id = await _user(container)
    await container.complete_integration(user_id, "google", "code")

    await container.import_google_calendar(user_id)

    [(_token, time_min, time_max)] = calendar.listed
    assert (time_max - time_min).days == ImportGoogleCalendar.DEFAULT_WINDOW_DAYS


async def test_import_google_calendar_honours_an_explicit_window() -> None:
    calendar = FakeCalendar([])
    container = build_test_container(calendar=calendar)
    user_id = await _user(container)
    await container.complete_integration(user_id, "google", "code")

    await container.import_google_calendar(user_id, days=7)

    [(_token, time_min, time_max)] = calendar.listed
    assert (time_max - time_min).days == 7


async def test_import_google_calendar_rejects_a_non_positive_window(
    container: ApiContainer,
) -> None:
    user_id = await _user(container)
    with pytest.raises(InvalidInput):
        await container.import_google_calendar(user_id, days=0)


async def test_import_google_calendar_requires_a_connection(container: ApiContainer) -> None:
    user_id = await _user(container)
    with pytest.raises(ReauthRequired):
        await container.import_google_calendar(user_id)


async def test_import_google_calendar_appears_in_the_import_list() -> None:
    container = build_test_container(calendar=FakeCalendar([_event()]))
    user_id = await _user(container)
    await container.complete_integration(user_id, "google", "code")
    view = await container.import_google_calendar(user_id)

    [listed] = await container.list_imports(user_id)
    assert listed.id == view.id
    assert listed.event_count == 1


# --- HTTP endpoint ---------------------------------------------------------------------


async def test_google_calendar_import_endpoint(
    client: httpx.AsyncClient, container: ApiContainer, auth_headers: dict[str, str]
) -> None:
    await client.post("/v1/integrations/google/callback", headers=auth_headers, json={"code": "c"})
    response = await client.post(
        "/v1/imports/google-calendar", headers=auth_headers, json={"days": 30}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "parsed"


async def test_google_calendar_import_endpoint_without_connection_returns_409(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post("/v1/imports/google-calendar", headers=auth_headers, json={})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "reauth_required"


# --- GoogleCalendar adapter (httpx.MockTransport) ---------------------------------------


def _calendar(transport: httpx.MockTransport) -> GoogleCalendar:
    return GoogleCalendar(client=httpx.AsyncClient(transport=transport))


async def test_google_calendar_list_events_reads_timed_and_all_day_events() -> None:
    seen: dict[str, str] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "ev-1",
                        "summary": "Standup",
                        "start": {"dateTime": "2026-03-01T09:00:00+00:00"},
                        "end": {"dateTime": "2026-03-01T09:30:00+00:00"},
                    },
                    {
                        "id": "ev-2",
                        "start": {"date": "2026-03-02"},
                        "end": {"date": "2026-03-03"},
                    },
                ]
            },
        )

    events = await _calendar(httpx.MockTransport(handle)).list_events(
        "at", NOW, NOW + timedelta(days=7)
    )

    assert seen["auth"] == "Bearer at"
    assert "timeMin=" in seen["url"]
    assert "singleEvents=true" in seen["url"]
    assert [e.external_id for e in events] == ["ev-1", "ev-2"]
    assert events[0].all_day is False
    assert events[0].end_at == datetime(2026, 3, 1, 9, 30, tzinfo=UTC)
    assert events[1].all_day is True
    assert events[1].summary == "(no title)"


async def test_google_calendar_list_events_follows_pagination() -> None:
    pages = iter(
        [
            httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "ev-1",
                            "summary": "a",
                            "start": {"dateTime": "2026-03-01T09:00:00Z"},
                            "end": {"dateTime": "2026-03-01T10:00:00Z"},
                        }
                    ],
                    "nextPageToken": "p2",
                },
            ),
            httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "ev-2",
                            "summary": "b",
                            "start": {"dateTime": "2026-03-02T09:00:00Z"},
                            "end": {"dateTime": "2026-03-02T10:00:00Z"},
                        }
                    ]
                },
            ),
        ]
    )
    transport = httpx.MockTransport(lambda _r: next(pages))
    events = await _calendar(transport).list_events("at", NOW, NOW + timedelta(days=7))
    assert [e.external_id for e in events] == ["ev-1", "ev-2"]


async def test_google_calendar_list_events_failure_raises() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(500, json={"error": "boom"}))
    with pytest.raises(DomainError):
        await _calendar(transport).list_events("at", NOW, NOW + timedelta(days=1))


async def test_google_calendar_create_event_sends_the_write_model() -> None:
    seen: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"id": "created-1"})

    event_id = await _calendar(httpx.MockTransport(handle)).create_event(
        "at",
        "cal-1",
        CalendarEventWrite(
            summary="Task",
            description="do it",
            start_at=NOW,
            end_at=NOW + timedelta(hours=1),
            all_day=False,
            color_id="5",
            private_props={"plan_id": "p1"},
        ),
    )

    assert event_id == "created-1"
    assert seen["url"] == "https://www.googleapis.com/calendar/v3/calendars/cal-1/events"
    body = str(seen["body"])
    assert '"colorId":"5"' in body.replace(" ", "")
    assert "plan_id" in body


async def test_google_calendar_create_calendar_returns_the_id() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={"id": "cal-9"}))
    assert await _calendar(transport).create_calendar("at", "My plan") == "cal-9"


async def test_google_calendar_all_day_write_uses_dates() -> None:
    seen: dict[str, str] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"id": "e"})

    await _calendar(httpx.MockTransport(handle)).update_event(
        "at",
        "cal-1",
        "ev-1",
        CalendarEventWrite(
            summary="Task",
            description="",
            start_at=NOW,
            end_at=NOW + timedelta(days=1),
            all_day=True,
        ),
    )
    assert '"date"' in seen["body"]
    assert "dateTime" not in seen["body"]


async def test_google_calendar_delete_helpers_accept_404() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(404, json={"error": "gone"}))
    await _calendar(transport).delete_event("at", "cal-1", "ev-1")
    await _calendar(transport).delete_calendar("at", "cal-1")


# --- FakeCalendar ------------------------------------------------------------------------


async def test_fake_calendar_records_every_write() -> None:
    fake = FakeCalendar([_event()])
    write = CalendarEventWrite(
        summary="s", description="d", start_at=NOW, end_at=NOW, all_day=False
    )

    calendar_id = await fake.create_calendar("at", "My plan")
    event_id = await fake.create_event("at", calendar_id, write)
    await fake.update_event("at", calendar_id, event_id, write)
    await fake.delete_event("at", calendar_id, event_id)
    await fake.delete_calendar("at", calendar_id)

    assert fake.created_calendars == ["My plan"]
    assert fake.created_events == [(calendar_id, write)]
    assert fake.updated_events == [(calendar_id, event_id, write)]
    assert fake.deleted_events == [(calendar_id, event_id)]
    assert fake.deleted_calendars == [calendar_id]


async def test_fake_calendar_can_raise_on_delete_calendar() -> None:
    fake = FakeCalendar([], delete_calendar_raises=DomainError("gone"))
    with pytest.raises(DomainError):
        await fake.delete_calendar("at", "cal-1")
