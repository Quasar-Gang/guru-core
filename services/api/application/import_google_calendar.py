"""Import the user's Google Calendar into a Document.

Unlike an upload there is no blob to keep, so this writes the document directly and the
import lands as `parsed` without ever touching storage or the `import.parse` queue.
"""

from datetime import timedelta
from uuid import UUID

from packages.importers import DocEvent
from packages.queue import ProfileBuildJobV1, QueuePort
from packages.repo import DocumentRepo, ImportRepo
from services.api.application.google_access_token import GoogleAccessTokenProvider
from services.api.application.list_imports import ImportView, to_view
from services.api.application.ports import CalendarPort, ClockPort
from services.api.domain.errors import InvalidInput

__all__ = ["ImportGoogleCalendar"]

SOURCE_GOOGLE_CALENDAR = "google_calendar"
FORMAT_ICS = "ics"
FILENAME = "google-calendar.ics"
STATUS_PARSED = "parsed"


class ImportGoogleCalendar:
    """Pull a forward-looking window of events and store them as one Document."""

    DEFAULT_WINDOW_DAYS = 90
    MAX_WINDOW_DAYS = 365

    def __init__(
        self,
        imports: ImportRepo,
        documents: DocumentRepo,
        calendar: CalendarPort,
        tokens: GoogleAccessTokenProvider,
        clock: ClockPort,
        queue: QueuePort,
    ) -> None:
        self._imports = imports
        self._documents = documents
        self._calendar = calendar
        self._tokens = tokens
        self._clock = clock
        self._queue = queue

    async def __call__(self, user_id: UUID, days: int = DEFAULT_WINDOW_DAYS) -> ImportView:
        if days <= 0 or days > self.MAX_WINDOW_DAYS:
            raise InvalidInput(f"days must be between 1 and {self.MAX_WINDOW_DAYS}")

        # Raises ReauthRequired before we create a row we would only have to fail.
        access_token = await self._tokens.get(user_id)
        time_min = self._clock.now()
        events = await self._calendar.list_events(
            access_token, time_min, time_min + timedelta(days=days)
        )

        record = await self._imports.create(
            user_id, SOURCE_GOOGLE_CALENDAR, FORMAT_ICS, "", FILENAME
        )
        document = await self._documents.create(
            record.id,
            [
                DocEvent(
                    title=event.summary,
                    start_at=event.start_at,
                    end_at=event.end_at,
                    all_day=event.all_day,
                    source_ref=event.external_id,
                ).model_dump(mode="json")
                for event in events
            ],
            [],
        )
        await self._imports.set_status(record.id, STATUS_PARSED)
        await self._queue.enqueue(ProfileBuildJobV1(user_id=user_id))
        return to_view(record.model_copy(update={"status": STATUS_PARSED}), document)
