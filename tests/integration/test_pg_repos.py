"""Integration tests for the Pg repos — they need a real PostgreSQL (`-m integration`).

Cleanup: each test creates its own user with a unique email / google_sub, and the `cleanup`
fixture removes them at teardown with `DELETE FROM users WHERE id IN (...)`, letting FK
ON DELETE CASCADE take the rest. role_models and llm_calls do not hang off a user, so they
are tracked and deleted separately by id and by unique prompt_name.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.repo import (
    LlmCallLog,
    NewPlan,
    NewPlanTask,
    Plan,
    TaskStatusUpdate,
    User,
    build_engine,
    build_session_factory,
)
from packages.repo import models as m
from packages.repo.pg.checkin import PgCheckinRepo
from packages.repo.pg.document import PgDocumentRepo
from packages.repo.pg.export import PgPlanExportRepo
from packages.repo.pg.followup import PgFollowupRoundRepo
from packages.repo.pg.imports import PgImportRepo
from packages.repo.pg.llm_call import PgLlmCallRepo
from packages.repo.pg.oauth import PgOAuthConnectionRepo
from packages.repo.pg.plan import PgPlanRepo
from packages.repo.pg.plan_session import PgPlanSessionRepo
from packages.repo.pg.plan_task import PgPlanTaskRepo
from packages.repo.pg.profile import PgProfileRepo
from packages.repo.pg.revision import PgPlanRevisionRepo
from packages.repo.pg.role_model import PgRoleModelRepo
from packages.repo.pg.user import PgUserRepo

pytestmark = pytest.mark.integration

DATABASE_URL = os.environ.get(
    "GURU_CORE_TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/guru_core",
)

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


@dataclass
class Cleanup:
    """Rows created by a test, deleted at teardown."""

    user_ids: list[UUID] = field(default_factory=list)
    role_model_ids: list[UUID] = field(default_factory=list)
    llm_prompt_names: list[str] = field(default_factory=list)


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = build_engine(DATABASE_URL)
    try:
        yield build_session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture
async def cleanup(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[Cleanup]:
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
            if tracker.llm_prompt_names:
                await session.execute(
                    delete(m.LlmCall).where(m.LlmCall.prompt_name.in_(tracker.llm_prompt_names))
                )
            await session.commit()


async def _make_user(session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup) -> User:
    token = uuid.uuid4().hex
    user = await PgUserRepo(session_factory).create(f"{token}@example.com", f"sub-{token}")
    cleanup.user_ids.append(user.id)
    return user


def _new_plan(user_id: UUID, session_id: UUID, title: str = "P") -> NewPlan:
    return NewPlan(
        user_id=user_id,
        session_id=session_id,
        title=title,
        difficulty="standard",
        goal_statement="ship it",
        duration_weeks=4,
        start_date=date(2026, 3, 1),
        deadline=date(2026, 3, 29),
        template={"key": "generic"},
        structure={"phases": []},
    )


def _new_task(
    *,
    start_at: datetime,
    template_key: str = "t",
    occurrence: int = 0,
    status: str = "pending",
) -> NewPlanTask:
    return NewPlanTask(
        template_key=template_key,
        week_index=0,
        occurrence=occurrence,
        task_type="study",
        title="task",
        start_at=start_at,
        end_at=start_at + timedelta(hours=1),
        status=status,
    )


async def _make_plan(
    session_factory: async_sessionmaker[AsyncSession],
    cleanup: Cleanup,
    *,
    title: str = "P",
) -> Plan:
    user = await _make_user(session_factory, cleanup)
    session = await PgPlanSessionRepo(session_factory).create(
        user.id, "goal", {}, [], False, None, None
    )
    [plan] = await PgPlanRepo(session_factory).create_many(
        [_new_plan(user.id, session.id, title=title)]
    )
    return plan


# --- The four key cases called out by the plan --------------------------------


async def test_plan_repo_scopes_by_user(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    plan = await _make_plan(session_factory, cleanup)
    other = await _make_user(session_factory, cleanup)
    repo = PgPlanRepo(session_factory)
    assert await repo.get(plan.user_id, plan.id) is not None
    assert await repo.get(other.id, plan.id) is None


async def test_plan_task_replace_from_keeps_history(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    plan = await _make_plan(session_factory, cleanup)
    repo = PgPlanTaskRepo(session_factory)
    await repo.replace_all(
        plan.id,
        [
            _new_task(start_at=NOW - timedelta(days=1), template_key="past"),
            _new_task(start_at=NOW + timedelta(days=1), template_key="f1"),
            _new_task(start_at=NOW + timedelta(days=2), template_key="f2"),
        ],
    )
    await repo.replace_from(
        plan.id, NOW, [_new_task(start_at=NOW + timedelta(days=3), template_key="new")]
    )
    keys = [t.template_key for t in await repo.list(plan.id, None, None)]
    assert keys == ["past", "new"]


async def test_revision_has_open_detects_pending_and_proposed(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    plan = await _make_plan(session_factory, cleanup)
    repo = PgPlanRevisionRepo(session_factory)
    assert await repo.has_open(plan.id) is False

    rev = await repo.create(plan.id, "shift", None)
    assert await repo.has_open(plan.id) is True

    await repo.set_proposal(rev.id, [{"a": 1}], [{"op": "add"}], "because")
    await repo.set_status(rev.id, "proposed", None)
    assert await repo.has_open(plan.id) is True

    await repo.set_status(rev.id, "accepted", NOW)
    assert await repo.has_open(plan.id) is False


async def test_counts_by_status_returns_all_four_keys(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    plan = await _make_plan(session_factory, cleanup)
    repo = PgPlanTaskRepo(session_factory)
    await repo.replace_all(plan.id, [_new_task(start_at=NOW, status="done")])
    counts = await repo.counts_by_status(plan.id)
    assert set(counts.keys()) == {"pending", "done", "missed", "skipped"}
    assert counts["done"] == 1
    assert counts["pending"] == 0


# --- UserRepo ---------------------------------------------------------------


async def test_user_repo_round_trip(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    repo = PgUserRepo(session_factory)
    user = await _make_user(session_factory, cleanup)
    assert await repo.get(user.id) == user
    assert await repo.get_by_google_sub(user.google_sub) == user
    assert await repo.get_by_google_sub(f"missing-{uuid.uuid4().hex}") is None
    assert await repo.get(uuid.uuid4()) is None


async def test_user_repo_isolates_users(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    a = await _make_user(session_factory, cleanup)
    b = await _make_user(session_factory, cleanup)
    repo = PgUserRepo(session_factory)
    assert a.id != b.id
    assert await repo.get_by_google_sub(a.google_sub) == a


# --- ProfileRepo ------------------------------------------------------------


async def test_profile_repo_round_trip(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    user = await _make_user(session_factory, cleanup)
    repo = PgProfileRepo(session_factory)
    assert await repo.get(user.id) is None

    created = await repo.upsert(user.id, {"age": 30}, "Asia/Taipei")
    assert await repo.get(user.id) == created

    updated = await repo.upsert(user.id, {"age": 31}, "UTC")
    assert updated.answers == {"age": 31}
    assert updated.timezone == "UTC"


async def test_profile_repo_isolates_users(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    a = await _make_user(session_factory, cleanup)
    b = await _make_user(session_factory, cleanup)
    repo = PgProfileRepo(session_factory)
    await repo.upsert(a.id, {"a": 1}, "UTC")
    assert await repo.get(b.id) is None


# --- OAuthConnectionRepo ----------------------------------------------------


async def test_oauth_repo_round_trip(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    user = await _make_user(session_factory, cleanup)
    repo = PgOAuthConnectionRepo(session_factory)
    conn = await repo.upsert(user.id, "google", b"tok", "scope-a", None)
    assert await repo.get(user.id, "google") == conn
    assert await repo.list_for_user(user.id) == [conn]

    again = await repo.upsert(user.id, "google", b"tok2", "scope-b", NOW)
    assert again.id == conn.id
    assert again.encrypted_refresh_token == b"tok2"
    assert len(await repo.list_for_user(user.id)) == 1

    await repo.mark_revoked(user.id, "google", NOW)
    revoked = await repo.get(user.id, "google")
    assert revoked is not None
    assert revoked.revoked_at == NOW


async def test_oauth_repo_isolates_users(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    a = await _make_user(session_factory, cleanup)
    b = await _make_user(session_factory, cleanup)
    repo = PgOAuthConnectionRepo(session_factory)
    await repo.upsert(a.id, "google", b"tok", "s", None)
    assert await repo.get(b.id, "google") is None
    assert await repo.list_for_user(b.id) == []


# --- ImportRepo / DocumentRepo ---------------------------------------------


async def test_import_repo_round_trip(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    user = await _make_user(session_factory, cleanup)
    repo = PgImportRepo(session_factory)
    imp = await repo.create(user.id, "upload", "csv", "key/1", "a.csv")
    assert imp.status == "pending"
    assert await repo.get(user.id, imp.id) == imp
    assert await repo.get_unscoped(imp.id) == imp

    await repo.set_status(imp.id, "failed", "boom")
    got = await repo.get(user.id, imp.id)
    assert got is not None
    assert (got.status, got.error) == ("failed", "boom")


async def test_import_repo_isolates_users(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    a = await _make_user(session_factory, cleanup)
    b = await _make_user(session_factory, cleanup)
    repo = PgImportRepo(session_factory)
    imp = await repo.create(a.id, "upload", "csv", "key/1", "a.csv")
    assert await repo.get(b.id, imp.id) is None
    assert await repo.list_for_user(b.id) == []
    assert await repo.list_for_user(a.id) == [imp]


async def test_document_repo_round_trip(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    user = await _make_user(session_factory, cleanup)
    imp = await PgImportRepo(session_factory).create(user.id, "upload", "csv", "k", "a.csv")
    repo = PgDocumentRepo(session_factory)
    doc = await repo.create(imp.id, [{"e": 1}], [{"t": "x"}])
    assert await repo.get_by_import(imp.id) == doc
    assert await repo.list_by_imports([imp.id]) == [doc]


async def test_document_repo_isolates_imports(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    user = await _make_user(session_factory, cleanup)
    imports = PgImportRepo(session_factory)
    a = await imports.create(user.id, "upload", "csv", "k1", "a.csv")
    repo = PgDocumentRepo(session_factory)
    doc = await repo.create(a.id, [], [])
    other = uuid.uuid4()
    assert await repo.get_by_import(other) is None
    assert await repo.list_by_imports([other]) == []
    assert await repo.list_by_imports([a.id, other]) == [doc]


# --- RoleModelRepo ----------------------------------------------------------


async def test_role_model_repo_round_trip(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    repo = PgRoleModelRepo(session_factory)
    tag = f"tag-{uuid.uuid4().hex}"
    rm = await repo.upsert(None, "trait", "Focus", [tag, "study"], {"summary": "s"})
    cleanup.role_model_ids.append(rm.id)
    assert await repo.get(rm.id) == rm
    assert rm.version == 1

    updated = await repo.upsert(rm.id, "trait", "Focus v2", [tag], {"summary": "s2"})
    assert updated.id == rm.id
    assert updated.version == 2
    assert updated.name == "Focus v2"
    assert tag in await repo.list_tags()

    await repo.deactivate(rm.id)
    assert [r.id for r in await repo.list(None, [tag], None)] == []
    assert [r.id for r in await repo.list(None, [tag], None, active_only=False)] == [rm.id]


async def test_role_model_repo_filters(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    repo = PgRoleModelRepo(session_factory)
    x, y, z = (f"t-{uuid.uuid4().hex}" for _ in range(3))
    a = await repo.upsert(None, "trait", "A", [x, y], {})
    b = await repo.upsert(None, "persona", "B", [y, z], {})
    cleanup.role_model_ids.extend([a.id, b.id])

    assert [r.id for r in await repo.list("trait", [y], None)] == [a.id]
    assert {r.id for r in await repo.list(None, [y], None)} == {a.id, b.id}
    assert [r.id for r in await repo.list(None, None, [y, z])] == [b.id]
    assert len(await repo.list(None, [y], None, limit=1)) == 1


# --- PlanSessionRepo / FollowupRoundRepo -----------------------------------


async def test_plan_session_repo_round_trip(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    user = await _make_user(session_factory, cleanup)
    imp = await PgImportRepo(session_factory).create(user.id, "upload", "csv", "k", "a.csv")
    repo = PgPlanSessionRepo(session_factory)
    s = await repo.create(user.id, "learn go", {"a": 1}, [imp.id], True, None, None)
    assert s.status == "collecting"
    assert s.import_ids == [imp.id]
    assert await repo.get(user.id, s.id) == s
    assert await repo.get_unscoped(s.id) == s

    assert await repo.bump_round(s.id) == 1
    assert await repo.bump_round(s.id) == 2
    await repo.set_status(s.id, "failed", "nope")
    await repo.set_context_snapshot(s.id, {"ctx": True})
    got = await repo.get(user.id, s.id)
    assert got is not None
    assert (got.status, got.error, got.round) == ("failed", "nope", 2)
    assert got.context_snapshot == {"ctx": True}
    assert got.import_ids == [imp.id]


async def test_plan_session_repo_isolates_users(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    a = await _make_user(session_factory, cleanup)
    b = await _make_user(session_factory, cleanup)
    repo = PgPlanSessionRepo(session_factory)
    s = await repo.create(a.id, "g", {}, [], False, None, None)
    assert await repo.get(b.id, s.id) is None


async def test_followup_round_repo_round_trip(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    user = await _make_user(session_factory, cleanup)
    sessions = PgPlanSessionRepo(session_factory)
    s1 = await sessions.create(user.id, "g", {}, [], False, None, None)
    repo = PgFollowupRoundRepo(session_factory)
    r1 = await repo.create(s1.id, 1, [{"q": "why"}])
    r2 = await repo.create(s1.id, 2, [{"q": "when"}])
    assert await repo.latest(s1.id) == r2
    assert await repo.list_for_session(s1.id) == [r1, r2]

    await repo.record_answers(r1.id, [{"a": "because"}], NOW)
    rounds = await repo.list_for_session(s1.id)
    assert rounds[0].answers == [{"a": "because"}]
    assert rounds[0].answered_at == NOW


async def test_followup_round_repo_isolates_sessions(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    user = await _make_user(session_factory, cleanup)
    sessions = PgPlanSessionRepo(session_factory)
    s1 = await sessions.create(user.id, "g", {}, [], False, None, None)
    s2 = await sessions.create(user.id, "g2", {}, [], False, None, None)
    repo = PgFollowupRoundRepo(session_factory)
    await repo.create(s1.id, 1, [])
    assert await repo.latest(s2.id) is None
    assert await repo.list_for_session(s2.id) == []


# --- PlanRepo ---------------------------------------------------------------


async def test_plan_repo_round_trip(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    user = await _make_user(session_factory, cleanup)
    session = await PgPlanSessionRepo(session_factory).create(
        user.id, "g", {}, [], False, None, None
    )
    repo = PgPlanRepo(session_factory)
    plans = await repo.create_many(
        [_new_plan(user.id, session.id, "a"), _new_plan(user.id, session.id, "b")]
    )
    assert len(plans) == 2
    p = plans[0]
    assert await repo.get_unscoped(p.id) is not None
    assert len(await repo.list_for_session(session.id)) == 2
    assert len(await repo.list_for_user(user.id, None)) == 2
    assert await repo.list_for_user(user.id, "active") == []

    updated = await repo.update_fields(p.id, status="active", activated_at=NOW)
    assert updated.status == "active"
    assert updated.activated_at == NOW
    assert len(await repo.list_for_user(user.id, "active")) == 1

    await repo.set_status_for_session(session.id, "archived", p.id)
    others = [x for x in await repo.list_for_session(session.id) if x.id != p.id]
    assert all(x.status == "archived" for x in others)
    still_active = await repo.get_unscoped(p.id)
    assert still_active is not None
    assert still_active.status == "active"

    await repo.delete(p.id)
    assert await repo.get_unscoped(p.id) is None


async def test_plan_repo_isolates_users(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    plan = await _make_plan(session_factory, cleanup)
    other = await _make_user(session_factory, cleanup)
    repo = PgPlanRepo(session_factory)
    assert await repo.list_for_user(other.id, None) == []
    assert await repo.get(other.id, plan.id) is None


# --- PlanTaskRepo -----------------------------------------------------------


async def test_plan_task_repo_round_trip(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    plan = await _make_plan(session_factory, cleanup)
    repo = PgPlanTaskRepo(session_factory)
    await repo.replace_all(
        plan.id,
        [
            _new_task(start_at=NOW, template_key="a"),
            _new_task(start_at=NOW + timedelta(days=5), template_key="b"),
        ],
    )
    tasks = await repo.list(plan.id, None, None)
    assert [t.template_key for t in tasks] == ["a", "b"]
    assert await repo.get(plan.id, tasks[0].id) == tasks[0]

    windowed = await repo.list(plan.id, NOW + timedelta(days=1), None)
    assert [t.template_key for t in windowed] == ["b"]

    updated = await repo.update_fields(tasks[0].id, status="done", completed_at=NOW)
    assert updated.status == "done"

    await repo.bulk_set_status(
        plan.id, [TaskStatusUpdate(task_id=tasks[1].id, status="missed", missed_reason="sick")]
    )
    after = await repo.get(plan.id, tasks[1].id)
    assert after is not None
    assert (after.status, after.missed_reason) == ("missed", "sick")

    assert len(await repo.list_dirty(plan.id)) == 2
    await repo.update_fields(tasks[0].id, synced_at=NOW + timedelta(days=1))
    assert {t.id for t in await repo.list_dirty(plan.id)} == {tasks[1].id}


async def test_plan_task_repo_isolates_plans(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    plan_a = await _make_plan(session_factory, cleanup, title="a")
    plan_b = await _make_plan(session_factory, cleanup, title="b")
    repo = PgPlanTaskRepo(session_factory)
    await repo.replace_all(plan_a.id, [_new_task(start_at=NOW)])
    [task] = await repo.list(plan_a.id, None, None)
    assert await repo.list(plan_b.id, None, None) == []
    assert await repo.get(plan_b.id, task.id) is None
    await repo.replace_all(plan_b.id, [])
    assert len(await repo.list(plan_a.id, None, None)) == 1


# --- CheckinRepo ------------------------------------------------------------


async def test_checkin_repo_round_trip(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    plan = await _make_plan(session_factory, cleanup)
    repo = PgCheckinRepo(session_factory)
    day = date(2026, 3, 2)
    c = await repo.upsert(plan.id, day, [{"task_id": "x", "status": "done"}], "good")
    assert await repo.list_for_plan(plan.id) == [c]
    c2 = await repo.upsert(plan.id, day, [], "better")
    assert c2.id == c.id
    assert await repo.list_for_plan(plan.id) == [c2]


async def test_checkin_repo_isolates_plans(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    plan_a = await _make_plan(session_factory, cleanup, title="a")
    plan_b = await _make_plan(session_factory, cleanup, title="b")
    repo = PgCheckinRepo(session_factory)
    await repo.upsert(plan_a.id, date(2026, 3, 2), [], None)
    assert await repo.list_for_plan(plan_b.id) == []


# --- PlanRevisionRepo -------------------------------------------------------


async def test_revision_repo_round_trip(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    plan = await _make_plan(session_factory, cleanup)
    repo = PgPlanRevisionRepo(session_factory)
    rev = await repo.create(plan.id, "compress", "too slow")
    assert rev.trigger == "manual"
    assert rev.status == "pending"
    assert await repo.get(plan.id, rev.id) == rev
    assert await repo.get_unscoped(rev.id) == rev
    assert await repo.list_for_plan(plan.id) == [rev]

    await repo.set_proposal(rev.id, [{"t": 1}], [{"op": "move"}], "why")
    got = await repo.get_unscoped(rev.id)
    assert got is not None
    assert got.proposed_tasks == [{"t": 1}]
    assert got.diff == [{"op": "move"}]
    assert got.rationale == "why"

    await repo.set_status(rev.id, "rejected", NOW)
    got2 = await repo.get_unscoped(rev.id)
    assert got2 is not None
    assert (got2.status, got2.decided_at) == ("rejected", NOW)


async def test_revision_repo_isolates_plans(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    plan_a = await _make_plan(session_factory, cleanup, title="a")
    plan_b = await _make_plan(session_factory, cleanup, title="b")
    repo = PgPlanRevisionRepo(session_factory)
    rev = await repo.create(plan_a.id, "shift", None)
    assert await repo.get(plan_b.id, rev.id) is None
    assert await repo.list_for_plan(plan_b.id) == []
    assert await repo.has_open(plan_b.id) is False


# --- PlanExportRepo ---------------------------------------------------------


async def test_export_repo_round_trip(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    plan = await _make_plan(session_factory, cleanup)
    repo = PgPlanExportRepo(session_factory)
    e = await repo.upsert(plan.id, "google_calendar", "queued", None, None, None)
    assert await repo.get(plan.id, "google_calendar") == e
    e2 = await repo.upsert(plan.id, "google_calendar", "synced", "cal-1", NOW, None)
    assert e2.id == e.id
    assert e2.external_calendar_id == "cal-1"
    assert await repo.list_for_plan(plan.id) == [e2]
    await repo.delete(plan.id, "google_calendar")
    assert await repo.get(plan.id, "google_calendar") is None


async def test_export_repo_isolates_plans(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    plan_a = await _make_plan(session_factory, cleanup, title="a")
    plan_b = await _make_plan(session_factory, cleanup, title="b")
    repo = PgPlanExportRepo(session_factory)
    await repo.upsert(plan_a.id, "google_calendar", "queued", None, None, None)
    assert await repo.get(plan_b.id, "google_calendar") is None
    assert await repo.list_for_plan(plan_b.id) == []


# --- LlmCallRepo ------------------------------------------------------------


async def test_llm_call_repo_round_trip(
    session_factory: async_sessionmaker[AsyncSession], cleanup: Cleanup
) -> None:
    prompt_name = f"t-{uuid.uuid4().hex}"
    cleanup.llm_prompt_names.append(prompt_name)
    repo = PgLlmCallRepo(session_factory)
    await repo.record(
        LlmCallLog(
            prompt_name=prompt_name,
            prompt_version="1",
            provider="fake",
            model="fake-1",
            purpose="plan",
            input_tokens=10,
            output_tokens=20,
            latency_ms=5,
        )
    )
    await repo.record(
        LlmCallLog(prompt_name=prompt_name, purpose="followup", degraded=True, job_id="j-1")
    )

    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(m.LlmCall)
                    .where(m.LlmCall.prompt_name == prompt_name)
                    .order_by(m.LlmCall.purpose)
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 2
    assert [r.purpose for r in rows] == ["followup", "plan"]
    assert rows[0].degraded is True
    assert rows[0].job_id == "j-1"
    assert rows[1].input_tokens == 10
    assert rows[1].attempts == 1
