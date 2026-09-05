"""One repo protocol per aggregate.

Most aggregates are a single table, so most protocols are a single table's worth of
methods. The exception is `PlanTreeRepo`: a Plan's Milestones, Tasks and Schedule Slots are
written and replaced together as one consistent whole, and splitting them into three
protocols would only invite a caller to write half a tree.

Every method touching user data takes a `user_id: UUID`, the exceptions being the role
model catalogue and the worker-only `*_unscoped` reads. Return types are always the frozen
Pydantic models from `entities.py`.
"""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, Protocol
from uuid import UUID

from packages.repo.entities import (
    Checkin,
    DirectionHypothesis,
    DirectionRun,
    Document,
    FitVerdict,
    Import,
    LlmCallLog,
    Milestone,
    NewFitVerdict,
    NewMilestone,
    NewReport,
    NewRoleModel,
    NewTask,
    OAuthConnection,
    Plan,
    PlanExport,
    Profile,
    QuestionAnswer,
    Quota,
    Reconciliation,
    Report,
    RoleModel,
    ScheduledTaskRow,
    Task,
    TaskStatusUpdate,
    User,
)


class UserRepo(Protocol):
    async def get_by_google_sub(self, google_sub: str) -> User | None: ...

    async def get(self, user_id: UUID) -> User | None: ...

    async def create(self, email: str, google_sub: str) -> User: ...


class OAuthConnectionRepo(Protocol):
    async def get(self, user_id: UUID, provider: str) -> OAuthConnection | None: ...

    async def list_for_user(self, user_id: UUID) -> list[OAuthConnection]: ...

    async def upsert(
        self,
        user_id: UUID,
        provider: str,
        encrypted_refresh_token: bytes,
        scopes: str,
        expires_at: datetime | None,
    ) -> OAuthConnection: ...

    async def mark_revoked(self, user_id: UUID, provider: str, at: datetime) -> None: ...


class ImportRepo(Protocol):
    async def create(
        self, user_id: UUID, source: str, format: str, storage_key: str, filename: str
    ) -> Import: ...

    async def get(self, user_id: UUID, import_id: UUID) -> Import | None: ...

    async def get_unscoped(self, import_id: UUID) -> Import | None: ...

    async def list_for_user(self, user_id: UUID) -> list[Import]: ...

    async def set_status(self, import_id: UUID, status: str, error: str | None = None) -> None: ...


class DocumentRepo(Protocol):
    async def create(
        self, import_id: UUID, events: list[dict[str, Any]], text_chunks: list[dict[str, Any]]
    ) -> Document: ...

    async def get_by_import(self, import_id: UUID) -> Document | None: ...

    async def list_by_imports(self, import_ids: Sequence[UUID]) -> list[Document]: ...


class ProfileRepo(Protocol):
    """One Profile per user, revised in place — hence `upsert` and no `create`."""

    async def get(self, user_id: UUID) -> Profile | None: ...

    async def upsert(
        self,
        user_id: UUID,
        timezone: str,
        signals: dict[str, Any],
        coverage: dict[str, Any],
        source_import_ids: Sequence[UUID],
    ) -> Profile: ...

    async def set_timezone(self, user_id: UUID, timezone: str) -> Profile: ...


class DirectionRunRepo(Protocol):
    async def create(self, user_id: UUID) -> DirectionRun: ...

    async def get(self, user_id: UUID, run_id: UUID) -> DirectionRun | None: ...

    async def get_unscoped(self, run_id: UUID) -> DirectionRun | None: ...

    async def latest(self, user_id: UUID) -> DirectionRun | None: ...

    async def set_status(self, run_id: UUID, status: str, error: str | None = None) -> None: ...

    async def set_period(self, run_id: UUID, period_start: date, period_end: date) -> None: ...

    async def set_readouts(self, run_id: UUID, readouts: dict[str, Any]) -> None: ...


class ReportRepo(Protocol):
    async def replace_for_run(
        self, user_id: UUID, run_id: UUID, reports: Sequence[NewReport]
    ) -> list[Report]: ...

    async def list_for_run(self, run_id: UUID) -> list[Report]: ...


class RoleModelRepo(Protocol):
    """The catalogue is not user data: the six shipped shapes are read by everyone.

    User-authored templates live in the same table with `author = "user"`, so the
    Recommender scores one catalogue rather than two.
    """

    async def get(self, role_model_id: UUID) -> RoleModel | None: ...

    async def get_by_code(self, code: str) -> RoleModel | None: ...

    async def list(
        self,
        author_user_id: UUID | None = None,
        tags_any: Sequence[str] | None = None,
        active_only: bool = True,
        limit: int = 50,
    ) -> builtins.list[RoleModel]: ...

    async def list_tags(self) -> builtins.list[str]: ...

    async def upsert(self, role_model: NewRoleModel) -> RoleModel: ...

    async def deactivate(self, role_model_id: UUID) -> None: ...


class FitVerdictRepo(Protocol):
    async def replace_for_run(
        self, user_id: UUID, run_id: UUID, verdicts: Sequence[NewFitVerdict]
    ) -> list[FitVerdict]: ...

    async def list_for_run(self, run_id: UUID) -> list[FitVerdict]: ...

    async def get(self, user_id: UUID, verdict_id: UUID) -> FitVerdict | None: ...


class QuestionAnswerRepo(Protocol):
    async def upsert(
        self, user_id: UUID, question_key: str, answer: str, skipped: bool, answered_at: datetime
    ) -> QuestionAnswer: ...

    async def list_for_user(self, user_id: UUID) -> list[QuestionAnswer]: ...


class QuotaRepo(Protocol):
    async def get(self, user_id: UUID) -> Quota | None: ...

    async def upsert(
        self, user_id: UUID, drop_first: str, weekly_minutes: int, effective_from: date
    ) -> Quota: ...


class DirectionHypothesisRepo(Protocol):
    """Append-only by construction: there is no update method to call.

    `append` allocates the next version for the user; a hypothesis, once written, is only
    ever read again.
    """

    async def append(
        self,
        user_id: UUID,
        role_model_id: UUID,
        fit_verdict_id: UUID,
        source: str,
        evidence_snapshot: dict[str, Any],
        drop_first: str | None,
        answers_count: int,
        review_date: date,
    ) -> DirectionHypothesis: ...

    async def get(self, user_id: UUID, hypothesis_id: UUID) -> DirectionHypothesis | None: ...

    async def get_unscoped(self, hypothesis_id: UUID) -> DirectionHypothesis | None: ...

    async def list_for_user(self, user_id: UUID) -> list[DirectionHypothesis]: ...

    async def latest(self, user_id: UUID) -> DirectionHypothesis | None: ...


class PlanRepo(Protocol):
    async def create(self, user_id: UUID, hypothesis_id: UUID) -> Plan: ...

    async def get(self, user_id: UUID, plan_id: UUID) -> Plan | None: ...

    async def get_unscoped(self, plan_id: UUID) -> Plan | None: ...

    async def get_by_hypothesis(self, hypothesis_id: UUID) -> Plan | None: ...

    async def list_for_user(self, user_id: UUID, status: str | None) -> list[Plan]: ...

    async def update_fields(self, plan_id: UUID, **fields: Any) -> Plan: ...


class PlanTreeRepo(Protocol):
    """The Plan's contents: the Milestone tree, its Tasks, and the Schedule they land on.

    `replace_tree` is the only write path that creates them, and it takes the whole tree at
    once. Milestones and Tasks name their parents by key rather than by id, so the Plan
    Engine can hand over a freshly generated tree without knowing any database identity.
    """

    async def replace_tree(
        self,
        plan_id: UUID,
        milestones: Sequence[NewMilestone],
        tasks: Sequence[NewTask],
    ) -> None: ...

    async def list_milestones(self, plan_id: UUID) -> list[Milestone]: ...

    async def list_scheduled(
        self, plan_id: UUID, start_from: datetime | None = None, start_to: datetime | None = None
    ) -> list[ScheduledTaskRow]: ...

    async def list_dirty(self, plan_id: UUID) -> list[ScheduledTaskRow]: ...

    async def get_task(self, plan_id: UUID, task_id: UUID) -> Task | None: ...

    async def find_task(self, task_id: UUID) -> ScheduledTaskRow | None: ...

    async def set_task_status(
        self, task_id: UUID, status: str, completed_at: datetime | None
    ) -> Task: ...

    async def bulk_set_status(self, plan_id: UUID, results: Sequence[TaskStatusUpdate]) -> None: ...

    async def counts_by_status(self, plan_id: UUID) -> dict[str, int]: ...

    async def mark_dirty(self, task_id: UUID) -> None:
        """Forget when this slot was last pushed, but keep where it was pushed to.

        Losing the external reference would make the next push create a duplicate event
        rather than update the one already on the calendar.
        """
        ...

    async def mark_synced(
        self, task_id: UUID, external_ref: str | None, synced_at: datetime | None
    ) -> None: ...


class CheckinRepo(Protocol):
    async def upsert(
        self,
        plan_id: UUID,
        checkin_date: date,
        task_results: list[dict[str, Any]],
        note: str | None,
    ) -> Checkin: ...

    async def list_for_plan(self, plan_id: UUID) -> list[Checkin]: ...


class PlanExportRepo(Protocol):
    async def get(self, plan_id: UUID, target: str) -> PlanExport | None: ...

    async def list_for_plan(self, plan_id: UUID) -> list[PlanExport]: ...

    async def upsert(
        self,
        plan_id: UUID,
        target: str,
        status: str,
        external_calendar_id: str | None,
        last_synced_at: datetime | None,
        error: str | None,
    ) -> PlanExport: ...

    async def delete(self, plan_id: UUID, target: str) -> None: ...


class ReconciliationRepo(Protocol):
    async def create(
        self, user_id: UUID, hypothesis_id: UUID, period_start: date, period_end: date
    ) -> Reconciliation: ...

    async def get(self, user_id: UUID, reconciliation_id: UUID) -> Reconciliation | None: ...

    async def get_unscoped(self, reconciliation_id: UUID) -> Reconciliation | None: ...

    async def list_for_hypothesis(self, hypothesis_id: UUID) -> list[Reconciliation]: ...

    async def complete(
        self,
        reconciliation_id: UUID,
        comparison: dict[str, Any],
        narrative: str,
        revision_kind: str | None,
    ) -> None: ...

    async def decide(self, reconciliation_id: UUID, outcome: str) -> None: ...

    async def fail(self, reconciliation_id: UUID, error: str) -> None: ...


class LlmCallRepo(Protocol):
    async def record(self, log: LlmCallLog) -> None: ...
