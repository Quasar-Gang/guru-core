"""Intake and export: the two ends of the pipeline that touch the outside world.

Both services drain the same in-memory queue here, so the chain an upload actually sets off
— parse, then rebuild the Profile — is exercised rather than asserted about.
"""

from pathlib import Path
from uuid import UUID

import pytest

from services.api.container import ApiContainer, create_worker_handlers
from services.engine.container import EngineContainer
from services.engine.container import create_worker_handlers as engine_handlers

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "importers"


@pytest.fixture
def handlers(container: ApiContainer, engine: EngineContainer) -> dict[str, object]:
    """Everything both workers serve, so the queue can be drained in one pass."""
    return {**create_worker_handlers(container), **engine_handlers(engine)}


async def drain(container: ApiContainer, handlers: dict[str, object]) -> None:
    """Run the queue until it is empty.

    One pass is not enough on purpose: a finished parse enqueues the Profile rebuild, and
    the point of these tests is that the chain runs itself.
    """
    while container.queue.enqueued:  # type: ignore[attr-defined]
        await container.queue.drain(handlers)  # type: ignore[attr-defined]


async def _upload_file(container: ApiContainer, user_id: UUID, name: str) -> UUID:
    data = (FIXTURES / name).read_bytes()
    presigned = await container.presign_import(user_id, name, "application/octet-stream", len(data))
    await container.storage.put(presigned.storage_key, data, "application/octet-stream")
    await container.complete_import(user_id, presigned.import_id)
    return presigned.import_id


class TestIntake:
    async def test_a_file_too_large_is_refused_before_it_is_uploaded(
        self, container: ApiContainer, auth_user_id: UUID
    ):
        from services.api.domain.errors import InvalidInput

        with pytest.raises(InvalidInput, match="20 MB"):
            await container.presign_import(auth_user_id, "big.csv", "text/csv", 40 * 1024 * 1024)

    async def test_an_unsupported_format_is_refused(
        self, container: ApiContainer, auth_user_id: UUID
    ):
        from services.api.domain.errors import InvalidInput

        with pytest.raises(InvalidInput):
            await container.presign_import(auth_user_id, "photo.tiff", "image/tiff", 10)

    async def test_completing_without_uploading_anything_is_refused(
        self, container: ApiContainer, auth_user_id: UUID
    ):
        from services.api.domain.errors import InvalidInput

        presigned = await container.presign_import(auth_user_id, "a.csv", "text/csv", 10)
        with pytest.raises(InvalidInput, match="no object was uploaded"):
            await container.complete_import(auth_user_id, presigned.import_id)

    async def test_an_upload_is_parsed_and_the_profile_rebuilt_from_it(
        self,
        container: ApiContainer,
        auth_user_id: UUID,
        handlers: dict[str, object],
    ):
        """One upload sets off the whole chain, and the Profile is revised in place."""
        await _upload_file(container, auth_user_id, "sample.ics")
        await drain(container, handlers)

        imports = await container.list_imports(auth_user_id)
        assert [row.status for row in imports] == ["parsed"]
        assert imports[0].event_count > 0

        profile = await container.read_profile(auth_user_id)
        assert profile.coverage["events"] == imports[0].event_count
        assert profile.coverage["sources"] == ["upload"]

    async def test_a_second_upload_sharpens_the_same_profile(
        self,
        container: ApiContainer,
        auth_user_id: UUID,
        handlers: dict[str, object],
    ):
        await _upload_file(container, auth_user_id, "sample.ics")
        await drain(container, handlers)
        first = await container.read_profile(auth_user_id)

        await _upload_file(container, auth_user_id, "sample.md")
        await drain(container, handlers)
        second = await container.read_profile(auth_user_id)

        assert second.coverage["text_chunks"] > first.coverage["text_chunks"]
        assert second.coverage["events"] == first.coverage["events"]

    async def test_a_file_the_parser_chokes_on_is_recorded_rather_than_retried(
        self,
        container: ApiContainer,
        auth_user_id: UUID,
        handlers: dict[str, object],
    ):
        presigned = await container.presign_import(auth_user_id, "broken.pdf", "application/pdf", 4)
        await container.storage.put(presigned.storage_key, b"not a pdf", "application/pdf")
        await container.complete_import(auth_user_id, presigned.import_id)
        await drain(container, handlers)

        imports = await container.list_imports(auth_user_id)
        assert imports[0].status == "failed"
        assert imports[0].error


class TestExport:
    @pytest.fixture
    async def draft_plan(
        self,
        container: ApiContainer,
        engine: EngineContainer,
        catalog,
        auth_user_id: UUID,
        handlers: dict[str, object],
    ) -> UUID:
        """A plan the whole way through the queue, exactly as a real client would get one."""
        from tests.application.test_the_loop import _upload

        await catalog.seed_catalog()
        await _upload(container, auth_user_id)
        await engine.build_profile(auth_user_id)
        await container.start_direction_run(auth_user_id)
        await drain(container, handlers)

        view = await container.get_direction_run(auth_user_id, None)
        hypothesis = await container.create_hypothesis(auth_user_id, view.verdicts[0].id)
        await drain(container, handlers)
        assert hypothesis.plan_id is not None
        return hypothesis.plan_id

    @pytest.fixture
    async def active_plan(
        self, container: ApiContainer, auth_user_id: UUID, draft_plan: UUID
    ) -> UUID:
        await container.set_plan_status(auth_user_id, draft_plan, "active")
        return draft_plan

    async def test_a_draft_plan_is_not_exported(
        self, container: ApiContainer, auth_user_id: UUID, draft_plan: UUID
    ):
        from services.api.domain.errors import Conflict

        with pytest.raises(Conflict, match="only an active plan"):
            await container.request_export(auth_user_id, draft_plan, "google_calendar")

    async def test_exporting_without_google_asks_for_the_connection(
        self, container: ApiContainer, auth_user_id: UUID, active_plan: UUID
    ):
        from services.api.domain.errors import ReauthRequired

        with pytest.raises(ReauthRequired):
            await container.request_export(auth_user_id, active_plan, "google_calendar")

    async def _connect(self, container: ApiContainer, user_id: UUID) -> None:
        await container.complete_integration(user_id, "google", "code")

    async def test_the_first_push_builds_the_plan_its_own_calendar(
        self,
        container: ApiContainer,
        auth_user_id: UUID,
        active_plan: UUID,
        handlers: dict[str, object],
    ):
        await self._connect(container, auth_user_id)
        result = await container.request_export(auth_user_id, active_plan, "google_calendar")
        assert result.mode == "full"
        await drain(container, handlers)

        assert container.calendar.created_calendars  # type: ignore[attr-defined]
        assert container.calendar.created_events  # type: ignore[attr-defined]
        status = await container.get_export_status(auth_user_id, active_plan)
        assert status[0].status == "synced"
        assert status[0].pending_changes == 0

    async def test_ticking_a_task_off_makes_exactly_that_slot_dirty(
        self,
        container: ApiContainer,
        auth_user_id: UUID,
        active_plan: UUID,
        handlers: dict[str, object],
    ):
        await self._connect(container, auth_user_id)
        await container.request_export(auth_user_id, active_plan, "google_calendar")
        await drain(container, handlers)

        tasks = await container.list_plan_tasks(auth_user_id, active_plan)
        await container.update_task_status(auth_user_id, active_plan, tasks[0].id, "done")
        status = await container.get_export_status(auth_user_id, active_plan)
        assert status[0].pending_changes == 1

        await drain(container, handlers)
        assert container.calendar.updated_events  # type: ignore[attr-defined]

    async def test_unexporting_removes_the_calendar_and_forgets_every_event(
        self,
        container: ApiContainer,
        auth_user_id: UUID,
        active_plan: UUID,
        handlers: dict[str, object],
    ):
        await self._connect(container, auth_user_id)
        await container.request_export(auth_user_id, active_plan, "google_calendar")
        await drain(container, handlers)

        await container.unexport_plan(auth_user_id, active_plan, "google_calendar")
        assert container.calendar.deleted_calendars  # type: ignore[attr-defined]
        assert await container.get_export_status(auth_user_id, active_plan) == []
