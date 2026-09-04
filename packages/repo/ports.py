"""每張表一個 Repo Protocol。

所有涉及使用者資料的方法都帶 `user_id: UUID`（`role_models` 與 worker 專用的
`*_unscoped` 讀取除外）。回傳型別一律是 `entities.py` 的 frozen Pydantic model。
"""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, Protocol
from uuid import UUID

from packages.repo.entities import (
    Checkin,
    Document,
    FollowupRound,
    Import,
    LlmCallLog,
    NewPlan,
    NewPlanTask,
    OAuthConnection,
    Plan,
    PlanExport,
    PlanRevision,
    PlanSession,
    PlanTask,
    Profile,
    RoleModel,
    TaskStatusUpdate,
    User,
)


class UserRepo(Protocol):
    async def get_by_google_sub(self, google_sub: str) -> User | None: ...

    async def get(self, user_id: UUID) -> User | None: ...

    async def create(self, email: str, google_sub: str) -> User: ...


class ProfileRepo(Protocol):
    async def get(self, user_id: UUID) -> Profile | None: ...

    async def upsert(self, user_id: UUID, answers: dict[str, Any], timezone: str) -> Profile: ...


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


class RoleModelRepo(Protocol):
    async def get(self, role_model_id: UUID) -> RoleModel | None: ...

    async def list(
        self,
        kind: str | None,
        tags_any: Sequence[str] | None,
        tags_all: Sequence[str] | None,
        active_only: bool = True,
        limit: int = 50,
    ) -> builtins.list[RoleModel]: ...

    async def list_tags(self) -> builtins.list[str]: ...

    async def upsert(
        self,
        role_model_id: UUID | None,
        kind: str,
        name: str,
        tags: builtins.list[str],
        content: dict[str, Any],
    ) -> RoleModel: ...

    async def deactivate(self, role_model_id: UUID) -> None: ...


class PlanSessionRepo(Protocol):
    async def create(
        self,
        user_id: UUID,
        goal: str,
        intake: dict[str, Any],
        import_ids: list[UUID],
        use_calendar: bool,
        trait_role_model_id: UUID | None,
        persona_role_model_id: UUID | None,
    ) -> PlanSession: ...

    async def get(self, user_id: UUID, session_id: UUID) -> PlanSession | None: ...

    async def get_unscoped(self, session_id: UUID) -> PlanSession | None: ...

    async def set_status(self, session_id: UUID, status: str, error: str | None = None) -> None: ...

    async def bump_round(self, session_id: UUID) -> int: ...

    async def set_context_snapshot(self, session_id: UUID, snapshot: dict[str, Any]) -> None: ...


class FollowupRoundRepo(Protocol):
    async def create(
        self, session_id: UUID, round_no: int, questions: list[dict[str, Any]]
    ) -> FollowupRound: ...

    async def latest(self, session_id: UUID) -> FollowupRound | None: ...

    async def list_for_session(self, session_id: UUID) -> list[FollowupRound]: ...

    async def record_answers(
        self, round_id: UUID, answers: list[dict[str, Any]], answered_at: datetime
    ) -> None: ...


class PlanRepo(Protocol):
    async def create_many(self, plans: Sequence[NewPlan]) -> list[Plan]: ...

    async def get(self, user_id: UUID, plan_id: UUID) -> Plan | None: ...

    async def get_unscoped(self, plan_id: UUID) -> Plan | None: ...

    async def list_for_user(self, user_id: UUID, status: str | None) -> list[Plan]: ...

    async def list_for_session(self, session_id: UUID) -> list[Plan]: ...

    async def update_fields(self, plan_id: UUID, **fields: Any) -> Plan: ...

    async def set_status_for_session(
        self, session_id: UUID, status: str, exclude_plan_id: UUID
    ) -> None: ...

    async def delete(self, plan_id: UUID) -> None: ...


class PlanTaskRepo(Protocol):
    async def replace_all(self, plan_id: UUID, tasks: Sequence[NewPlanTask]) -> None: ...

    async def replace_from(
        self, plan_id: UUID, cutoff: datetime, tasks: Sequence[NewPlanTask]
    ) -> None: ...

    async def list(
        self, plan_id: UUID, start_from: datetime | None, start_to: datetime | None
    ) -> builtins.list[PlanTask]: ...

    async def get(self, plan_id: UUID, task_id: UUID) -> PlanTask | None: ...

    async def update_fields(self, task_id: UUID, **fields: Any) -> PlanTask: ...

    async def bulk_set_status(self, plan_id: UUID, results: Sequence[TaskStatusUpdate]) -> None: ...

    async def counts_by_status(self, plan_id: UUID) -> dict[str, int]: ...

    async def list_dirty(self, plan_id: UUID) -> builtins.list[PlanTask]: ...


class CheckinRepo(Protocol):
    async def upsert(
        self,
        plan_id: UUID,
        checkin_date: date,
        task_results: list[dict[str, Any]],
        note: str | None,
    ) -> Checkin: ...

    async def list_for_plan(self, plan_id: UUID) -> list[Checkin]: ...


class PlanRevisionRepo(Protocol):
    async def create(self, plan_id: UUID, strategy: str, note: str | None) -> PlanRevision: ...

    async def get(self, plan_id: UUID, revision_id: UUID) -> PlanRevision | None: ...

    async def get_unscoped(self, revision_id: UUID) -> PlanRevision | None: ...

    async def list_for_plan(self, plan_id: UUID) -> list[PlanRevision]: ...

    async def has_open(self, plan_id: UUID) -> bool: ...

    async def set_proposal(
        self,
        revision_id: UUID,
        proposed_tasks: list[dict[str, Any]],
        diff: list[dict[str, Any]],
        rationale: str,
    ) -> None: ...

    async def set_status(
        self, revision_id: UUID, status: str, decided_at: datetime | None
    ) -> None: ...


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


class LlmCallRepo(Protocol):
    async def record(self, log: LlmCallLog) -> None: ...
