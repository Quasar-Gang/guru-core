"""InMemory repo 的 round-trip 與跨使用者/跨計畫隔離測試。"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from packages.repo import (
    InMemoryCheckinRepo,
    InMemoryDocumentRepo,
    InMemoryFollowupRoundRepo,
    InMemoryImportRepo,
    InMemoryLlmCallRepo,
    InMemoryOAuthConnectionRepo,
    InMemoryPlanExportRepo,
    InMemoryPlanRepo,
    InMemoryPlanRevisionRepo,
    InMemoryPlanSessionRepo,
    InMemoryPlanTaskRepo,
    InMemoryProfileRepo,
    InMemoryRoleModelRepo,
    InMemoryUserRepo,
    LlmCallLog,
    NewPlan,
    NewPlanTask,
    TaskStatusUpdate,
)

U1 = UUID("11111111-1111-1111-1111-111111111111")
U2 = UUID("22222222-2222-2222-2222-222222222222")
S1 = UUID("33333333-3333-3333-3333-333333333333")
S2 = UUID("44444444-4444-4444-4444-444444444444")

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _new_plan(user_id: UUID = U1, session_id: UUID = S1, title: str = "P") -> NewPlan:
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


# --- 計畫給定的四個重點案例 -------------------------------------------------


async def test_plan_repo_scopes_by_user() -> None:
    repo = InMemoryPlanRepo()
    [p] = await repo.create_many([_new_plan(user_id=U1)])
    assert await repo.get(U1, p.id) is not None
    assert await repo.get(U2, p.id) is None


async def test_plan_task_replace_from_keeps_history() -> None:
    repo = InMemoryPlanTaskRepo()
    plan_id = uuid.uuid4()
    await repo.replace_all(
        plan_id,
        [
            _new_task(start_at=NOW - timedelta(days=1), template_key="past"),
            _new_task(start_at=NOW + timedelta(days=1), template_key="f1"),
            _new_task(start_at=NOW + timedelta(days=2), template_key="f2"),
        ],
    )
    await repo.replace_from(
        plan_id, NOW, [_new_task(start_at=NOW + timedelta(days=3), template_key="new")]
    )
    keys = [t.template_key for t in await repo.list(plan_id, None, None)]
    assert keys == ["past", "new"]


async def test_revision_has_open_detects_pending_and_proposed() -> None:
    repo = InMemoryPlanRevisionRepo()
    plan_id = uuid.uuid4()
    assert await repo.has_open(plan_id) is False

    rev = await repo.create(plan_id, "shift", None)
    assert await repo.has_open(plan_id) is True

    await repo.set_proposal(rev.id, [{"a": 1}], [{"op": "add"}], "because")
    await repo.set_status(rev.id, "proposed", None)
    assert await repo.has_open(plan_id) is True

    await repo.set_status(rev.id, "accepted", NOW)
    assert await repo.has_open(plan_id) is False


async def test_counts_by_status_returns_all_four_keys() -> None:
    repo = InMemoryPlanTaskRepo()
    plan_id = uuid.uuid4()
    await repo.replace_all(plan_id, [_new_task(start_at=NOW, status="done")])
    counts = await repo.counts_by_status(plan_id)
    assert set(counts.keys()) == {"pending", "done", "missed", "skipped"}
    assert counts["done"] == 1
    assert counts["pending"] == 0


# --- UserRepo ---------------------------------------------------------------


async def test_user_repo_round_trip() -> None:
    repo = InMemoryUserRepo()
    user = await repo.create("a@example.com", "sub-1")
    assert await repo.get(user.id) == user
    assert await repo.get_by_google_sub("sub-1") == user


async def test_user_repo_isolates_users() -> None:
    repo = InMemoryUserRepo()
    a = await repo.create("a@example.com", "sub-a")
    b = await repo.create("b@example.com", "sub-b")
    assert a.id != b.id
    assert await repo.get_by_google_sub("sub-a") == a
    assert await repo.get_by_google_sub("missing") is None


# --- ProfileRepo ------------------------------------------------------------


async def test_profile_repo_round_trip() -> None:
    repo = InMemoryProfileRepo()
    assert await repo.get(U1) is None
    p = await repo.upsert(U1, {"age": 30}, "Asia/Taipei")
    assert await repo.get(U1) == p
    p2 = await repo.upsert(U1, {"age": 31}, "UTC")
    assert p2.answers == {"age": 31}
    assert p2.timezone == "UTC"


async def test_profile_repo_isolates_users() -> None:
    repo = InMemoryProfileRepo()
    await repo.upsert(U1, {"a": 1}, "UTC")
    assert await repo.get(U2) is None


# --- OAuthConnectionRepo ----------------------------------------------------


async def test_oauth_repo_round_trip() -> None:
    repo = InMemoryOAuthConnectionRepo()
    conn = await repo.upsert(U1, "google", b"tok", "scope-a", None)
    assert await repo.get(U1, "google") == conn
    assert await repo.list_for_user(U1) == [conn]

    again = await repo.upsert(U1, "google", b"tok2", "scope-b", NOW)
    assert again.id == conn.id
    assert len(await repo.list_for_user(U1)) == 1

    await repo.mark_revoked(U1, "google", NOW)
    revoked = await repo.get(U1, "google")
    assert revoked is not None
    assert revoked.revoked_at == NOW


async def test_oauth_repo_isolates_users() -> None:
    repo = InMemoryOAuthConnectionRepo()
    await repo.upsert(U1, "google", b"tok", "s", None)
    assert await repo.get(U2, "google") is None
    assert await repo.list_for_user(U2) == []


# --- ImportRepo / DocumentRepo ---------------------------------------------


async def test_import_repo_round_trip() -> None:
    repo = InMemoryImportRepo()
    imp = await repo.create(U1, "upload", "csv", "key/1", "a.csv")
    assert imp.status == "pending"
    assert await repo.get(U1, imp.id) == imp
    assert await repo.get_unscoped(imp.id) == imp
    await repo.set_status(imp.id, "failed", "boom")
    got = await repo.get(U1, imp.id)
    assert got is not None
    assert (got.status, got.error) == ("failed", "boom")


async def test_import_repo_isolates_users() -> None:
    repo = InMemoryImportRepo()
    imp = await repo.create(U1, "upload", "csv", "key/1", "a.csv")
    assert await repo.get(U2, imp.id) is None
    assert await repo.list_for_user(U2) == []
    assert await repo.list_for_user(U1) == [imp]


async def test_document_repo_round_trip() -> None:
    repo = InMemoryDocumentRepo()
    import_id = uuid.uuid4()
    doc = await repo.create(import_id, [{"e": 1}], [{"t": "x"}])
    assert await repo.get_by_import(import_id) == doc
    assert await repo.list_by_imports([import_id]) == [doc]


async def test_document_repo_isolates_imports() -> None:
    repo = InMemoryDocumentRepo()
    a = await repo.create(uuid.uuid4(), [], [])
    other = uuid.uuid4()
    assert await repo.get_by_import(other) is None
    assert await repo.list_by_imports([other]) == []
    assert await repo.list_by_imports([a.import_id, other]) == [a]


# --- RoleModelRepo ----------------------------------------------------------


async def test_role_model_repo_round_trip() -> None:
    repo = InMemoryRoleModelRepo()
    rm = await repo.upsert(None, "trait", "Focus", ["discipline", "study"], {"summary": "s"})
    assert await repo.get(rm.id) == rm
    assert rm.version == 1

    updated = await repo.upsert(rm.id, "trait", "Focus v2", ["discipline"], {"summary": "s2"})
    assert updated.id == rm.id
    assert updated.version == 2
    assert await repo.list_tags() == ["discipline"]

    await repo.deactivate(rm.id)
    assert await repo.list(None, None, None) == []
    assert len(await repo.list(None, None, None, active_only=False)) == 1


async def test_role_model_repo_filters() -> None:
    repo = InMemoryRoleModelRepo()
    a = await repo.upsert(None, "trait", "A", ["x", "y"], {})
    b = await repo.upsert(None, "persona", "B", ["y", "z"], {})

    assert [r.id for r in await repo.list("trait", None, None)] == [a.id]
    assert {r.id for r in await repo.list(None, ["y"], None)} == {a.id, b.id}
    assert [r.id for r in await repo.list(None, None, ["y", "z"])] == [b.id]
    assert len(await repo.list(None, None, None, limit=1)) == 1


# --- PlanSessionRepo / FollowupRoundRepo -----------------------------------


async def test_plan_session_repo_round_trip() -> None:
    repo = InMemoryPlanSessionRepo()
    imp = uuid.uuid4()
    s = await repo.create(U1, "learn go", {"a": 1}, [imp], True, None, None)
    assert s.status == "collecting"
    assert s.import_ids == [imp]
    assert await repo.get(U1, s.id) == s
    assert await repo.get_unscoped(s.id) == s

    assert await repo.bump_round(s.id) == 1
    assert await repo.bump_round(s.id) == 2
    await repo.set_status(s.id, "failed", "nope")
    await repo.set_context_snapshot(s.id, {"ctx": True})
    got = await repo.get(U1, s.id)
    assert got is not None
    assert (got.status, got.error, got.round) == ("failed", "nope", 2)
    assert got.context_snapshot == {"ctx": True}


async def test_plan_session_repo_isolates_users() -> None:
    repo = InMemoryPlanSessionRepo()
    s = await repo.create(U1, "g", {}, [], False, None, None)
    assert await repo.get(U2, s.id) is None


async def test_followup_round_repo_round_trip() -> None:
    repo = InMemoryFollowupRoundRepo()
    r1 = await repo.create(S1, 1, [{"q": "why"}])
    r2 = await repo.create(S1, 2, [{"q": "when"}])
    assert await repo.latest(S1) == r2
    assert await repo.list_for_session(S1) == [r1, r2]

    await repo.record_answers(r1.id, [{"a": "because"}], NOW)
    rounds = await repo.list_for_session(S1)
    assert rounds[0].answers == [{"a": "because"}]
    assert rounds[0].answered_at == NOW


async def test_followup_round_repo_isolates_sessions() -> None:
    repo = InMemoryFollowupRoundRepo()
    await repo.create(S1, 1, [])
    assert await repo.latest(S2) is None
    assert await repo.list_for_session(S2) == []


# --- PlanRepo ---------------------------------------------------------------


async def test_plan_repo_round_trip() -> None:
    repo = InMemoryPlanRepo()
    plans = await repo.create_many([_new_plan(title="a"), _new_plan(title="b")])
    assert len(plans) == 2
    p = plans[0]
    assert await repo.get_unscoped(p.id) is not None
    assert len(await repo.list_for_session(S1)) == 2
    assert len(await repo.list_for_user(U1, None)) == 2
    assert await repo.list_for_user(U1, "active") == []

    updated = await repo.update_fields(p.id, status="active", activated_at=NOW)
    assert updated.status == "active"
    await repo.set_status_for_session(S1, "archived", p.id)
    others = [x for x in await repo.list_for_session(S1) if x.id != p.id]
    assert all(x.status == "archived" for x in others)

    await repo.delete(p.id)
    assert await repo.get_unscoped(p.id) is None


async def test_plan_repo_isolates_users() -> None:
    repo = InMemoryPlanRepo()
    [p] = await repo.create_many([_new_plan(user_id=U1)])
    assert await repo.list_for_user(U2, None) == []
    assert await repo.get(U2, p.id) is None


# --- PlanTaskRepo -----------------------------------------------------------


async def test_plan_task_repo_round_trip() -> None:
    repo = InMemoryPlanTaskRepo()
    plan_id = uuid.uuid4()
    await repo.replace_all(
        repo_plan_id := plan_id,
        [
            _new_task(start_at=NOW, template_key="a"),
            _new_task(start_at=NOW + timedelta(days=5), template_key="b"),
        ],
    )
    tasks = await repo.list(repo_plan_id, None, None)
    assert [t.template_key for t in tasks] == ["a", "b"]
    assert await repo.get(plan_id, tasks[0].id) == tasks[0]

    windowed = await repo.list(plan_id, NOW + timedelta(days=1), None)
    assert [t.template_key for t in windowed] == ["b"]

    updated = await repo.update_fields(tasks[0].id, status="done", completed_at=NOW)
    assert updated.status == "done"

    await repo.bulk_set_status(
        plan_id, [TaskStatusUpdate(task_id=tasks[1].id, status="missed", missed_reason="sick")]
    )
    after = await repo.get(plan_id, tasks[1].id)
    assert after is not None
    assert (after.status, after.missed_reason) == ("missed", "sick")

    assert len(await repo.list_dirty(plan_id)) == 2
    await repo.update_fields(tasks[0].id, synced_at=NOW + timedelta(days=1))
    assert {t.id for t in await repo.list_dirty(plan_id)} == {tasks[1].id}


async def test_plan_task_repo_isolates_plans() -> None:
    repo = InMemoryPlanTaskRepo()
    plan_a, plan_b = uuid.uuid4(), uuid.uuid4()
    await repo.replace_all(plan_a, [_new_task(start_at=NOW)])
    [task] = await repo.list(plan_a, None, None)
    assert await repo.list(plan_b, None, None) == []
    assert await repo.get(plan_b, task.id) is None
    await repo.replace_all(plan_b, [])
    assert len(await repo.list(plan_a, None, None)) == 1


# --- CheckinRepo ------------------------------------------------------------


async def test_checkin_repo_round_trip() -> None:
    repo = InMemoryCheckinRepo()
    plan_id = uuid.uuid4()
    day = date(2026, 3, 2)
    c = await repo.upsert(plan_id, day, [{"task_id": "x", "status": "done"}], "good")
    assert await repo.list_for_plan(plan_id) == [c]
    c2 = await repo.upsert(plan_id, day, [], "better")
    assert c2.id == c.id
    assert await repo.list_for_plan(plan_id) == [c2]


async def test_checkin_repo_isolates_plans() -> None:
    repo = InMemoryCheckinRepo()
    await repo.upsert(uuid.uuid4(), date(2026, 3, 2), [], None)
    assert await repo.list_for_plan(uuid.uuid4()) == []


# --- PlanRevisionRepo -------------------------------------------------------


async def test_revision_repo_round_trip() -> None:
    repo = InMemoryPlanRevisionRepo()
    plan_id = uuid.uuid4()
    rev = await repo.create(plan_id, "compress", "too slow")
    assert await repo.get(plan_id, rev.id) == rev
    assert await repo.get_unscoped(rev.id) == rev
    assert await repo.list_for_plan(plan_id) == [rev]

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


async def test_revision_repo_isolates_plans() -> None:
    repo = InMemoryPlanRevisionRepo()
    rev = await repo.create(uuid.uuid4(), "shift", None)
    other = uuid.uuid4()
    assert await repo.get(other, rev.id) is None
    assert await repo.list_for_plan(other) == []
    assert await repo.has_open(other) is False


# --- PlanExportRepo ---------------------------------------------------------


async def test_export_repo_round_trip() -> None:
    repo = InMemoryPlanExportRepo()
    plan_id = uuid.uuid4()
    e = await repo.upsert(plan_id, "google_calendar", "queued", None, None, None)
    assert await repo.get(plan_id, "google_calendar") == e
    e2 = await repo.upsert(plan_id, "google_calendar", "synced", "cal-1", NOW, None)
    assert e2.id == e.id
    assert await repo.list_for_plan(plan_id) == [e2]
    await repo.delete(plan_id, "google_calendar")
    assert await repo.get(plan_id, "google_calendar") is None


async def test_export_repo_isolates_plans() -> None:
    repo = InMemoryPlanExportRepo()
    plan_id = uuid.uuid4()
    await repo.upsert(plan_id, "google_calendar", "queued", None, None, None)
    other = uuid.uuid4()
    assert await repo.get(other, "google_calendar") is None
    assert await repo.list_for_plan(other) == []


# --- LlmCallRepo ------------------------------------------------------------


def _log(**over: Any) -> LlmCallLog:
    base: dict[str, Any] = {
        "prompt_name": "evaluate",
        "prompt_version": "1",
        "provider": "fake",
        "model": "fake-1",
        "purpose": "plan",
        "input_tokens": 10,
        "output_tokens": 20,
        "latency_ms": 5,
    }
    base.update(over)
    return LlmCallLog(**base)


async def test_llm_call_repo_round_trip() -> None:
    repo = InMemoryLlmCallRepo()
    await repo.record(_log())
    await repo.record(_log(prompt_name="followup", degraded=True))
    assert [r.prompt_name for r in repo.records] == ["evaluate", "followup"]
    assert repo.records[1].degraded is True
    assert repo.records[0].attempts == 1
