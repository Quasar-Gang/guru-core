"""The whole loop, end to end through fakes: upload, read, choose, plan, reconcile.

No database, no Redis, no network. The Engine and the API share the same in-memory repos,
exactly as they share one PostgreSQL in production, so a job the API queues can be run here
and its result read back through the API.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from packages.importers.document import DocEvent, Document, TextChunk
from services.api.container import ApiContainer
from services.catalog.container import CatalogContainer
from services.engine.container import EngineContainer

SIX = ("S-1", "S-2", "S-3", "S-4", "S-5", "S-6")


async def _upload(container: ApiContainer, user_id: UUID) -> None:
    """Two sources: a calendar and a resume. Two are enough to begin."""
    start = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
    document = Document(
        events=[
            DocEvent(
                title="Design review",
                start_at=start + timedelta(days=index * 7),
                end_at=start + timedelta(days=index * 7, hours=1),
                source_ref=f"e{index}",
            )
            for index in range(3)
        ],
        text_chunks=[TextChunk(text="Product Designer, 28 months, user interviews.")],
    )
    record = await container.imports.create(user_id, "upload", "ics", "key", "calendar.ics")
    await container.documents.create(
        record.id,
        [event.model_dump(mode="json") for event in document.events],
        [chunk.model_dump(mode="json") for chunk in document.text_chunks],
    )
    await container.imports.set_status(record.id, "parsed")


@pytest.fixture
async def seeded(catalog: CatalogContainer) -> None:
    await catalog.seed_catalog()


@pytest.fixture
async def ready(
    container: ApiContainer,
    engine: EngineContainer,
    auth_user_id: UUID,
    seeded: None,
) -> UUID:
    """A user whose data has been read and whose shapes have been scored."""
    await _upload(container, auth_user_id)
    await engine.build_profile(auth_user_id)
    run = await container.start_direction_run(auth_user_id)
    await engine.run_direction(run.id)
    return auth_user_id


class TestStationOne:
    async def test_the_profile_is_built_from_the_uploads_and_there_is_only_one(
        self, container: ApiContainer, engine: EngineContainer, auth_user_id: UUID
    ):
        await _upload(container, auth_user_id)
        await engine.build_profile(auth_user_id)
        await engine.build_profile(auth_user_id)

        profile = await container.read_profile(auth_user_id)
        assert profile.coverage["events"] == 3
        assert profile.coverage["sources"] == ["upload"]
        assert profile.signals["skills"]

    async def test_an_analysis_needs_something_to_read_first(
        self, container: ApiContainer, auth_user_id: UUID
    ):
        from services.api.domain.errors import Conflict

        with pytest.raises(Conflict, match="upload something first"):
            await container.start_direction_run(auth_user_id)

    async def test_the_run_produces_reports_then_a_verdict_for_every_shape(
        self, container: ApiContainer, ready: UUID
    ):
        view = await container.get_direction_run(ready, None)
        assert view.status == "ready"
        assert view.readouts["trajectory"]
        assert {report.dimension for report in view.reports} >= {"work", "unclassified"}
        assert [verdict.role_model_code for verdict in view.verdicts] == list(SIX)

    async def test_every_verdict_carries_five_cited_items_and_one_probe(
        self, container: ApiContainer, ready: UUID
    ):
        view = await container.get_direction_run(ready, None)
        dimensions = {report.dimension for report in view.reports}
        for verdict in view.verdicts:
            assert len(verdict.evidence) == 5
            assert {item["stance"] for item in verdict.evidence} == {"for", "against"}
            assert all(item["cites"]["dimension"] in dimensions for item in verdict.evidence)
            assert verdict.probe["statement"] and verdict.probe["cost"]

    async def test_a_second_run_cannot_start_while_one_is_in_flight(
        self, container: ApiContainer, auth_user_id: UUID, engine: EngineContainer
    ):
        from services.api.domain.errors import Conflict

        await _upload(container, auth_user_id)
        await engine.build_profile(auth_user_id)
        await container.start_direction_run(auth_user_id)
        with pytest.raises(Conflict, match="already"):
            await container.start_direction_run(auth_user_id)


class TestTheQuestions:
    async def test_all_three_are_offered_with_their_purpose(
        self, container: ApiContainer, auth_user_id: UUID
    ):
        questions = await container.list_questions(auth_user_id)
        assert [item.key for item in questions] == ["q1", "q2", "q3"]
        assert all(item.purpose for item in questions)

    async def test_skipping_is_recorded_as_an_answer(
        self, container: ApiContainer, auth_user_id: UUID
    ):
        await container.answer_question(auth_user_id, "q1", "", skipped=True)
        questions = await container.list_questions(auth_user_id)
        assert questions[0].skipped is True

    async def test_answering_q3_writes_the_quota(self, container: ApiContainer, auth_user_id: UUID):
        await container.answer_question(auth_user_id, "q3", "health", skipped=False)
        quota = await container.get_quota(auth_user_id)
        assert quota.drop_first == "health"
        assert quota.weekly_minutes > 0

    async def test_skipping_q3_leaves_no_quota_behind(
        self, container: ApiContainer, auth_user_id: UUID
    ):
        from services.api.domain.errors import NotFound

        await container.answer_question(auth_user_id, "q3", "", skipped=True)
        with pytest.raises(NotFound):
            await container.get_quota(auth_user_id)


class TestStationTwo:
    @pytest.fixture
    async def planned(self, container: ApiContainer, engine: EngineContainer, ready: UUID) -> UUID:
        await container.answer_question(ready, "q3", "career", skipped=False)
        view = await container.get_direction_run(ready, None)
        hypothesis = await container.create_hypothesis(ready, view.verdicts[0].id)
        assert hypothesis.plan_id is not None
        await engine.generate_plan(hypothesis.plan_id)
        return hypothesis.plan_id

    async def test_the_hypothesis_starts_at_v0_and_carries_its_evidence(
        self, container: ApiContainer, ready: UUID
    ):
        view = await container.get_direction_run(ready, None)
        created = await container.create_hypothesis(ready, view.verdicts[0].id)
        assert created.version == 0
        assert created.evidence_snapshot["probe"]
        assert created.evidence_snapshot["cost"]
        assert created.review_date > created.created_at.date()

    async def test_a_second_hypothesis_is_a_new_version_not_an_edit(
        self, container: ApiContainer, ready: UUID
    ):
        view = await container.get_direction_run(ready, None)
        first = await container.create_hypothesis(ready, view.verdicts[0].id)
        second = await container.create_hypothesis(ready, view.verdicts[1].id)
        assert (first.version, second.version) == (0, 1)
        stored = await container.list_hypotheses(ready)
        assert [row.version for row in stored] == [0, 1]
        assert stored[0].role_model_id != stored[1].role_model_id

    async def test_the_plan_is_a_tree_of_milestones(
        self, container: ApiContainer, ready: UUID, planned: UUID
    ):
        plan = await container.get_plan(ready, planned)
        assert plan.status == "draft"
        assert plan.title
        assert [node.key for node in plan.milestones] == ["probe"]
        assert [child.key for child in plan.milestones[0].children] == ["draft"]

    async def test_the_tasks_are_flat_and_placed_on_real_dates(
        self, container: ApiContainer, ready: UUID, planned: UUID
    ):
        tasks = await container.list_plan_tasks(ready, planned)
        assert tasks
        assert all(task.milestone_id for task in tasks)
        assert all(task.start_at < task.end_at or task.all_day for task in tasks)
        assert tasks == sorted(tasks, key=lambda task: task.start_at)

    async def test_the_plan_says_what_it_had_to_assume(
        self, container: ApiContainer, ready: UUID, planned: UUID
    ):
        plan = await container.get_plan(ready, planned)
        assert plan.structure["assumptions"]
        assert plan.structure["quota"]["drop_first"] == "career"

    async def test_ticking_a_task_off_is_recorded_once(
        self, container: ApiContainer, ready: UUID, planned: UUID
    ):
        tasks = await container.list_plan_tasks(ready, planned)
        updated = await container.update_task_status(ready, planned, tasks[0].id, "done")
        assert updated.status == "done"
        assert updated.completed_at is not None


class TestStationThree:
    @pytest.fixture
    async def reviewed(
        self, container: ApiContainer, engine: EngineContainer, ready: UUID
    ) -> tuple[UUID, UUID]:
        """A quarter run, then reviewed: hypothesis id and reconciliation id."""
        await container.answer_question(ready, "q2", "I stopped running after six weeks.", False)
        view = await container.get_direction_run(ready, None)
        hypothesis = await container.create_hypothesis(ready, view.verdicts[0].id)
        assert hypothesis.plan_id is not None
        await engine.generate_plan(hypothesis.plan_id)

        tasks = await container.list_plan_tasks(ready, hypothesis.plan_id)
        for task in tasks[:3]:
            await container.update_task_status(ready, hypothesis.plan_id, task.id, "done")

        review = await container.start_reconciliation(ready, hypothesis.id)
        await engine.reconcile(review.id)
        return hypothesis.id, review.id

    async def test_the_review_compares_and_narrates_but_does_not_decide(
        self, container: ApiContainer, ready: UUID, reviewed: tuple[UUID, UUID]
    ):
        view = await container.get_reconciliation(ready, reviewed[1])
        assert view.status == "done"
        assert view.comparison["execution"]["done"] == 3
        assert view.narrative
        assert view.outcome is None, "the decision belongs to the user"

    async def test_a_plan_that_never_changed_is_not_classified(
        self, container: ApiContainer, ready: UUID, reviewed: tuple[UUID, UUID]
    ):
        view = await container.get_reconciliation(ready, reviewed[1])
        assert view.comparison["schedule_changes"] == []
        assert view.revision_kind is None

    async def test_answering_revise_appends_the_next_version(
        self, container: ApiContainer, ready: UUID, reviewed: tuple[UUID, UUID]
    ):
        decided = await container.decide_reconciliation(ready, reviewed[1], "revise")
        assert decided.outcome == "revise"
        assert decided.next_hypothesis_id is not None

        versions = await container.list_hypotheses(ready)
        assert [row.version for row in versions] == [0, 1]
        assert versions[0].source != versions[1].source
        assert "revised after" in versions[1].source

    async def test_v0_is_untouched_by_the_revision(
        self, container: ApiContainer, ready: UUID, reviewed: tuple[UUID, UUID]
    ):
        """A hypothesis you can quietly edit can never be falsified."""
        before = await container.get_hypothesis(ready, reviewed[0])
        await container.decide_reconciliation(ready, reviewed[1], "revise")
        after = await container.get_hypothesis(ready, reviewed[0])
        assert before.model_dump(exclude={"plan_id"}) == after.model_dump(exclude={"plan_id"})

    async def test_the_question_may_only_be_answered_once(
        self, container: ApiContainer, ready: UUID, reviewed: tuple[UUID, UUID]
    ):
        from services.api.domain.errors import Conflict

        await container.decide_reconciliation(ready, reviewed[1], "holds")
        with pytest.raises(Conflict, match="already answered"):
            await container.decide_reconciliation(ready, reviewed[1], "replace")

    async def test_a_review_still_running_cannot_be_answered(
        self, container: ApiContainer, ready: UUID
    ):
        from services.api.domain.errors import Conflict

        view = await container.get_direction_run(ready, None)
        hypothesis = await container.create_hypothesis(ready, view.verdicts[0].id)
        review = await container.start_reconciliation(ready, hypothesis.id)
        with pytest.raises(Conflict, match="nothing to answer yet"):
            await container.decide_reconciliation(ready, review.id, "holds")
