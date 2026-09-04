"""The data types on the repo boundary — all frozen Pydantic models.

Read types (`User`, `Plan`, ...) mirror the ORM columns in `models.py` one for one. Write
types (`NewPlan`, `NewPlanTask`, `TaskStatusUpdate`, `LlmCallLog`) carry only the fields a
caller has to supply. ORM objects must never cross the repo boundary.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _Entity(BaseModel):
    """Immutable base class shared by every type a repo returns."""

    model_config = ConfigDict(frozen=True)


class User(_Entity):
    id: UUID
    email: str
    google_sub: str
    created_at: datetime


class Profile(_Entity):
    user_id: UUID
    answers: dict[str, Any]
    timezone: str
    updated_at: datetime


class OAuthConnection(_Entity):
    id: UUID
    user_id: UUID
    provider: str
    encrypted_refresh_token: bytes
    scopes: str
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class Import(_Entity):
    id: UUID
    user_id: UUID
    source: str
    format: str
    storage_key: str
    filename: str
    status: str
    error: str | None
    created_at: datetime


class Document(_Entity):
    id: UUID
    import_id: UUID
    events: list[dict[str, Any]]
    text_chunks: list[dict[str, Any]]
    created_at: datetime


class RoleModel(_Entity):
    id: UUID
    kind: str
    name: str
    tags: list[str]
    content: dict[str, Any]
    active: bool
    version: int
    created_at: datetime
    updated_at: datetime


class PlanSession(_Entity):
    id: UUID
    user_id: UUID
    trait_role_model_id: UUID | None
    persona_role_model_id: UUID | None
    goal: str
    intake: dict[str, Any]
    import_ids: list[UUID]
    use_calendar: bool
    status: str
    round: int
    context_snapshot: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class FollowupRound(_Entity):
    id: UUID
    session_id: UUID
    round_no: int
    questions: list[dict[str, Any]]
    answers: list[dict[str, Any]] | None
    answered_at: datetime | None
    created_at: datetime


class Plan(_Entity):
    id: UUID
    user_id: UUID
    session_id: UUID
    title: str
    difficulty: str
    status: str
    goal_statement: str
    duration_weeks: int
    start_date: date
    deadline: date
    template: dict[str, Any]
    structure: dict[str, Any]
    activated_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PlanTask(_Entity):
    id: UUID
    plan_id: UUID
    template_key: str
    week_index: int
    phase_index: int
    occurrence: int
    task_type: str
    title: str
    description: str
    start_at: datetime
    end_at: datetime
    all_day: bool
    status: str
    completed_at: datetime | None
    missed_reason: str | None
    external_ref: str | None
    synced_at: datetime | None
    sort_order: int


class Checkin(_Entity):
    id: UUID
    plan_id: UUID
    checkin_date: date
    task_results: list[dict[str, Any]]
    note: str | None
    created_at: datetime


class PlanRevision(_Entity):
    id: UUID
    plan_id: UUID
    trigger: str
    strategy: str
    trigger_detail: dict[str, Any] | None
    proposed_tasks: list[dict[str, Any]] | None
    diff: list[dict[str, Any]] | None
    rationale: str | None
    status: str
    created_at: datetime
    decided_at: datetime | None


class PlanExport(_Entity):
    id: UUID
    plan_id: UUID
    target: str
    external_calendar_id: str | None
    last_synced_at: datetime | None
    status: str
    error: str | None
    created_at: datetime


# --- Write-side input models -------------------------------------------------


class NewPlan(_Entity):
    """Input to `PlanRepo.create_many`."""

    user_id: UUID
    session_id: UUID
    title: str
    difficulty: str
    status: str = "draft"
    goal_statement: str
    duration_weeks: int
    start_date: date
    deadline: date
    template: dict[str, Any] = Field(default_factory=dict)
    structure: dict[str, Any] = Field(default_factory=dict)


class NewPlanTask(_Entity):
    """Input to `PlanTaskRepo.replace_all` / `replace_from`; `plan_id` is a method argument."""

    template_key: str
    week_index: int
    phase_index: int = 0
    occurrence: int = 0
    task_type: str
    title: str
    description: str = ""
    start_at: datetime
    end_at: datetime
    all_day: bool = False
    status: str = "pending"
    completed_at: datetime | None = None
    missed_reason: str | None = None
    external_ref: str | None = None
    synced_at: datetime | None = None
    sort_order: int = 0


class TaskStatusUpdate(_Entity):
    """One entry of the input to `PlanTaskRepo.bulk_set_status`."""

    task_id: UUID
    status: str
    completed_at: datetime | None = None
    missed_reason: str | None = None


class LlmCallLog(_Entity):
    """Input to `LlmCallRepo.record`; llm_calls is append-only."""

    prompt_name: str
    prompt_version: str = ""
    provider: str = ""
    model: str = ""
    purpose: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    attempts: int = 1
    degraded: bool = False
    job_id: str | None = None
