"""The PostgreSQL repos against a real database (`make integration`).

Every fake has a real implementation behind the same protocol, and this is where the real
one is held to it. The cases that matter are the ones a fake cannot prove: the append-only
constraint, the tree written in one transaction, and the join a schedule read depends on.

Cleanup: each test creates its own user with a unique email and sub, and the `cleanup`
fixture deletes them at teardown, letting `ON DELETE CASCADE` take the rest. Role models do
not hang off a user, so they are tracked and deleted by id.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.repo import (
    NewFitVerdict,
    NewMilestone,
    NewReport,
    NewRoleModel,
    NewTask,
    User,
    build_engine,
    build_session_factory,
)
from packages.repo import models as m
from packages.repo.pg.catalog import PgRoleModelRepo
from packages.repo.pg.direction import (
    PgDirectionHypothesisRepo,
    PgDirectionRunRepo,
    PgFitVerdictRepo,
    PgQuestionAnswerRepo,
    PgQuotaRepo,
    PgReportRepo,
)
from packages.repo.pg.identity import PgUserRepo
from packages.repo.pg.intake import PgProfileRepo
from packages.repo.pg.planning import PgPlanRepo, PgPlanTreeRepo

pytestmark = pytest.mark.integration

DATABASE_URL = os.environ.get(
    "GURU_CORE_TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/guru_core",
)

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
START = date(2026, 1, 5)


@dataclass
class Cleanup:
    user_ids: list[UUID] = field(default_factory=list)
    role_model_ids: list[UUID] = field(default_factory=list)


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = build_engine(DATABASE_URL)
    try:
        yield build_session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture
async def cleanup(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[Cleanup]:
    tracker = Cleanup()
    try:
        yield tracker
    finally:
        async with session_factory() as session:
            if tracker.user_ids:
                await session.execute(delete(m.User).where(m.User.id.in_(tracker.user_ids)))
            if tracker.role_model_ids:
                await session.execute(
                    delete(m.RoleModel).where(m.RoleModel.id.in_(tracker.role_model_ids))
                )
            await session.commit()


@pytest.fixture
async def user(session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup) -> User:
    suffix = uuid.uuid4().hex[:12]
    created = await PgUserRepo(session_factory).create(f"{suffix}@example.test", f"sub-{suffix}")
    cleanup.user_ids.append(created.id)
    return created


@pytest.fixture
async def role_model(session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup) -> UUID:
    created = await PgRoleModelRepo(session_factory).upsert(
        NewRoleModel(
            code=f"T-{uuid.uuid4().hex[:6]}",
            name="A shape",
            vision="v",
            five_year_path="p",
            must_accumulate="a",
            cost="Something it costs.",
            tags=["shape:depth"],
        )
    )
    cleanup.role_model_ids.append(created.id)
    return created.id


async def _verdict(
    session_factory: async_sessionmaker[AsyncSession], user: User, role_model_id: UUID
) -> tuple[UUID, UUID]:
    """A run with one report and one verdict; returns (run_id, verdict_id)."""
    run = await PgDirectionRunRepo(session_factory).create(user.id)
    await PgReportRepo(session_factory).replace_for_run(
        user.id,
        run.id,
        [NewReport(dimension="work", period_start=START, period_end=START, metrics={"share": 0.6})],
    )
    verdicts = await PgFitVerdictRepo(session_factory).replace_for_run(
        user.id,
        run.id,
        [
            NewFitVerdict(
                role_model_id=role_model_id,
                fit="strongly_consistent",
                verdict="A finding.",
                evidence=[{"stance": "for", "text": "t", "cites": {"dimension": "work"}}],
                probe={"statement": "s", "cost": "c"},
            )
        ],
    )
    return run.id, verdicts[0].id


class TestOneProfilePerUser:
    async def test_upsert_revises_in_place(
        self, session_factory: async_sessionmaker[AsyncSession], user: User
    ):
        repo = PgProfileRepo(session_factory)
        await repo.upsert(user.id, "UTC", {"a": 1}, {"events": 1}, [])
        second = await repo.upsert(user.id, "Asia/Taipei", {"a": 2}, {"events": 9}, [])
        assert second.timezone == "Asia/Taipei"
        assert second.coverage == {"events": 9}

    async def test_setting_a_timezone_creates_the_row_if_it_is_missing(
        self, session_factory: async_sessionmaker[AsyncSession], user: User
    ):
        stored = await PgProfileRepo(session_factory).set_timezone(user.id, "Europe/Berlin")
        assert stored.timezone == "Europe/Berlin"
        assert stored.signals == {}


class TestTheAppendOnlyHypothesis:
    async def test_versions_are_allocated_in_order(
        self, session_factory: async_sessionmaker[AsyncSession], user: User, role_model: UUID
    ):
        _, verdict_id = await _verdict(session_factory, user, role_model)
        repo = PgDirectionHypothesisRepo(session_factory)
        first = await repo.append(
            user_id=user.id,
            role_model_id=role_model,
            fit_verdict_id=verdict_id,
            source="s",
            evidence_snapshot={"a": 1},
            drop_first="career",
            answers_count=1,
            review_date=START,
        )
        second = await repo.append(
            user_id=user.id,
            role_model_id=role_model,
            fit_verdict_id=verdict_id,
            source="s",
            evidence_snapshot={"a": 2},
            drop_first="career",
            answers_count=2,
            review_date=START,
        )
        assert (first.version, second.version) == (0, 1)
        assert [row.version for row in await repo.list_for_user(user.id)] == [0, 1]
        latest = await repo.latest(user.id)
        assert latest is not None and latest.version == 1

    async def test_the_earlier_version_is_untouched(
        self, session_factory: async_sessionmaker[AsyncSession], user: User, role_model: UUID
    ):
        _, verdict_id = await _verdict(session_factory, user, role_model)
        repo = PgDirectionHypothesisRepo(session_factory)
        first = await repo.append(
            user_id=user.id,
            role_model_id=role_model,
            fit_verdict_id=verdict_id,
            source="v0",
            evidence_snapshot={"predicted": True},
            drop_first=None,
            answers_count=0,
            review_date=START,
        )
        await repo.append(
            user_id=user.id,
            role_model_id=role_model,
            fit_verdict_id=verdict_id,
            source="v1",
            evidence_snapshot={"predicted": False},
            drop_first=None,
            answers_count=0,
            review_date=START,
        )
        assert (await repo.get(user.id, first.id)) == first


class TestThePlanTree:
    async def test_a_tree_is_written_whole_and_read_back_with_its_schedule(
        self, session_factory: async_sessionmaker[AsyncSession], user: User, role_model: UUID
    ):
        _, verdict_id = await _verdict(session_factory, user, role_model)
        hypothesis = await PgDirectionHypothesisRepo(session_factory).append(
            user_id=user.id,
            role_model_id=role_model,
            fit_verdict_id=verdict_id,
            source="s",
            evidence_snapshot={},
            drop_first=None,
            answers_count=0,
            review_date=START,
        )
        plan = await PgPlanRepo(session_factory).create(user.id, hypothesis.id)
        tree = PgPlanTreeRepo(session_factory)
        await tree.replace_tree(
            plan.id,
            [
                NewMilestone(key="probe", title="Probe", metric="m", depth=0, position=0),
                NewMilestone(
                    key="draft", parent_key="probe", title="Draft", metric="m", depth=1, position=0
                ),
            ],
            [
                NewTask(
                    milestone_key="draft",
                    key="writing",
                    week_index=week,
                    area="career",
                    task_type="session",
                    title="Writing block",
                    duration_minutes=60,
                    start_at=NOW + timedelta(days=7 * week),
                    end_at=NOW + timedelta(days=7 * week, hours=1),
                )
                for week in range(3)
            ],
        )

        milestones = await tree.list_milestones(plan.id)
        assert [(row.key, row.depth) for row in milestones] == [("probe", 0), ("draft", 1)]
        assert milestones[1].parent_id == milestones[0].id

        scheduled = await tree.list_scheduled(plan.id)
        assert [row.task.week_index for row in scheduled] == [0, 1, 2]
        assert all(row.slot.task_id == row.task.id for row in scheduled)

    async def test_replacing_a_tree_leaves_nothing_of_the_old_one(
        self, session_factory: async_sessionmaker[AsyncSession], user: User, role_model: UUID
    ):
        _, verdict_id = await _verdict(session_factory, user, role_model)
        hypothesis = await PgDirectionHypothesisRepo(session_factory).append(
            user_id=user.id,
            role_model_id=role_model,
            fit_verdict_id=verdict_id,
            source="s",
            evidence_snapshot={},
            drop_first=None,
            answers_count=0,
            review_date=START,
        )
        plan = await PgPlanRepo(session_factory).create(user.id, hypothesis.id)
        tree = PgPlanTreeRepo(session_factory)
        milestone = NewMilestone(key="probe", title="Probe", metric="m")
        task = NewTask(
            milestone_key="probe",
            key="writing",
            week_index=0,
            area="career",
            task_type="session",
            title="Writing block",
            duration_minutes=60,
            start_at=NOW,
            end_at=NOW + timedelta(hours=1),
        )
        twice = [task, task.model_copy(update={"occurrence": 1})]
        await tree.replace_tree(plan.id, [milestone], twice)
        await tree.replace_tree(plan.id, [milestone], [task])

        assert len(await tree.list_scheduled(plan.id)) == 1
        assert len(await tree.list_milestones(plan.id)) == 1

    async def test_a_finished_task_is_dirty_until_it_is_pushed_again(
        self, session_factory: async_sessionmaker[AsyncSession], user: User, role_model: UUID
    ):
        _, verdict_id = await _verdict(session_factory, user, role_model)
        hypothesis = await PgDirectionHypothesisRepo(session_factory).append(
            user_id=user.id,
            role_model_id=role_model,
            fit_verdict_id=verdict_id,
            source="s",
            evidence_snapshot={},
            drop_first=None,
            answers_count=0,
            review_date=START,
        )
        plan = await PgPlanRepo(session_factory).create(user.id, hypothesis.id)
        tree = PgPlanTreeRepo(session_factory)
        await tree.replace_tree(
            plan.id,
            [NewMilestone(key="probe", title="Probe", metric="m")],
            [
                NewTask(
                    milestone_key="probe",
                    key="writing",
                    week_index=0,
                    area="career",
                    task_type="session",
                    title="Writing block",
                    duration_minutes=60,
                    start_at=NOW,
                    end_at=NOW + timedelta(hours=1),
                )
            ],
        )
        task = (await tree.list_scheduled(plan.id))[0].task
        assert len(await tree.list_dirty(plan.id)) == 1

        await tree.mark_synced(task.id, "event-1", NOW)
        assert await tree.list_dirty(plan.id) == []

        await tree.set_task_status(task.id, "done", NOW + timedelta(hours=2))
        assert len(await tree.list_dirty(plan.id)) == 1

        # A task that changed keeps its calendar event; only the sync stamp is forgotten,
        # so the next push updates that event rather than creating a duplicate.
        await tree.mark_dirty(task.id)
        found = await tree.find_task(task.id)
        assert found is not None
        assert found.slot.external_ref == "event-1"
        assert found.slot.synced_at is None


class TestTheCatalogue:
    async def test_upserting_by_code_revises_rather_than_duplicates(
        self, session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
    ):
        repo = PgRoleModelRepo(session_factory)
        code = f"T-{uuid.uuid4().hex[:6]}"
        first = await repo.upsert(
            NewRoleModel(
                code=code,
                name="First",
                vision="v",
                five_year_path="p",
                must_accumulate="a",
                cost="c",
            )
        )
        cleanup.role_model_ids.append(first.id)
        second = await repo.upsert(
            NewRoleModel(
                code=code,
                name="Second",
                vision="v",
                five_year_path="p",
                must_accumulate="a",
                cost="c",
            )
        )
        assert second.id == first.id
        assert (second.name, second.version) == ("Second", first.version + 1)

    async def test_a_user_sees_the_shipped_shapes_and_only_their_own(
        self, session_factory: async_sessionmaker[AsyncSession], user: User, cleanup: Cleanup
    ):
        repo = PgRoleModelRepo(session_factory)
        mine = await repo.upsert(
            NewRoleModel(
                code=f"U-{uuid.uuid4().hex[:6]}",
                name="Mine",
                vision="v",
                five_year_path="p",
                must_accumulate="a",
                cost="c",
                author="user",
                author_user_id=user.id,
            )
        )
        cleanup.role_model_ids.append(mine.id)
        assert mine.id in {row.id for row in await repo.list(author_user_id=user.id, limit=200)}
        assert mine.id not in {row.id for row in await repo.list(limit=200)}


class TestAnswersAndQuota:
    async def test_an_answer_is_replaced_rather_than_appended(
        self, session_factory: async_sessionmaker[AsyncSession], user: User
    ):
        repo = PgQuestionAnswerRepo(session_factory)
        await repo.upsert(user.id, "q1", "No management.", False, NOW)
        await repo.upsert(user.id, "q1", "", True, NOW)
        rows = await repo.list_for_user(user.id)
        assert len(rows) == 1
        assert rows[0].skipped is True

    async def test_the_quota_is_one_row_per_user(
        self, session_factory: async_sessionmaker[AsyncSession], user: User
    ):
        repo = PgQuotaRepo(session_factory)
        await repo.upsert(user.id, "career", 300, START)
        stored = await repo.upsert(user.id, "health", 120, START)
        assert (stored.drop_first, stored.weekly_minutes) == ("health", 120)
