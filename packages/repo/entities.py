"""The data types on the repo boundary — all frozen Pydantic models.

Read types (`User`, `Plan`, ...) mirror the ORM columns in `models.py` one for one. Write
types (`NewReport`, `NewMilestone`, `NewTask`, ...) carry only the fields a caller has to
supply. ORM objects must never cross the repo boundary.

JSONB columns stay as plain dicts here on purpose. The shapes inside them — an evidence
item, a probe, a milestone tree — are domain concepts with domain invariants, so they are
typed and validated in `services/*/domain` and only then handed over as data.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _Entity(BaseModel):
    """Immutable base class shared by every type a repo returns."""

    model_config = ConfigDict(frozen=True)


# --- Identity and intake -----------------------------------------------------


class User(_Entity):
    id: UUID
    email: str
    google_sub: str
    created_at: datetime


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


class Profile(_Entity):
    user_id: UUID
    timezone: str
    signals: dict[str, Any]
    coverage: dict[str, Any]
    source_import_ids: list[UUID]
    updated_at: datetime


# --- Station 1 ---------------------------------------------------------------


class DirectionRun(_Entity):
    id: UUID
    user_id: UUID
    status: str
    period_start: date | None
    period_end: date | None
    readouts: dict[str, Any]
    error: str | None
    created_at: datetime
    updated_at: datetime


class Report(_Entity):
    id: UUID
    user_id: UUID
    run_id: UUID
    dimension: str
    period_start: date
    period_end: date
    metrics: dict[str, Any]
    findings: dict[str, Any]
    created_at: datetime


class RoleModel(_Entity):
    id: UUID
    code: str
    name: str
    vision: str
    five_year_path: str
    must_accumulate: str
    cost: str
    tags: list[str]
    author: str
    author_user_id: UUID | None
    active: bool
    version: int
    created_at: datetime
    updated_at: datetime


class FitVerdict(_Entity):
    id: UUID
    user_id: UUID
    run_id: UUID
    role_model_id: UUID
    fit: str
    verdict: str
    note: str
    evidence: list[dict[str, Any]]
    probe: dict[str, Any]
    created_at: datetime


class QuestionAnswer(_Entity):
    id: UUID
    user_id: UUID
    question_key: str
    answer: str
    skipped: bool
    answered_at: datetime


class Quota(_Entity):
    user_id: UUID
    drop_first: str
    weekly_minutes: int
    effective_from: date
    updated_at: datetime


class DirectionHypothesis(_Entity):
    id: UUID
    user_id: UUID
    version: int
    role_model_id: UUID
    fit_verdict_id: UUID
    source: str
    evidence_snapshot: dict[str, Any]
    drop_first: str | None
    answers_count: int
    review_date: date
    created_at: datetime


# --- Station 2 ---------------------------------------------------------------


class Plan(_Entity):
    id: UUID
    user_id: UUID
    hypothesis_id: UUID
    title: str
    status: str
    start_date: date | None
    duration_weeks: int
    structure: dict[str, Any]
    error: str | None
    activated_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class Milestone(_Entity):
    id: UUID
    plan_id: UUID
    parent_id: UUID | None
    key: str
    title: str
    metric: str
    target_date: date | None
    depth: int
    position: int
    status: str


class Task(_Entity):
    id: UUID
    plan_id: UUID
    milestone_id: UUID
    key: str
    week_index: int
    occurrence: int
    area: str
    task_type: str
    title: str
    description: str
    duration_minutes: int
    status: str
    completed_at: datetime | None
    sort_order: int


class ScheduleSlot(_Entity):
    id: UUID
    plan_id: UUID
    task_id: UUID
    start_at: datetime
    end_at: datetime
    all_day: bool
    external_ref: str | None
    synced_at: datetime | None


class Checkin(_Entity):
    id: UUID
    plan_id: UUID
    checkin_date: date
    task_results: list[dict[str, Any]]
    note: str | None
    created_at: datetime


class PlanExport(_Entity):
    id: UUID
    plan_id: UUID
    target: str
    external_calendar_id: str | None
    last_synced_at: datetime | None
    status: str
    error: str | None
    created_at: datetime


# --- Station 3 ---------------------------------------------------------------


class Reconciliation(_Entity):
    id: UUID
    user_id: UUID
    hypothesis_id: UUID
    status: str
    period_start: date
    period_end: date
    comparison: dict[str, Any]
    narrative: str
    outcome: str | None
    revision_kind: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime


# --- Write-side input models -------------------------------------------------


class NewReport(_Entity):
    """Input to `ReportRepo.replace_for_run`; `user_id` and `run_id` are method arguments."""

    dimension: str
    period_start: date
    period_end: date
    metrics: dict[str, Any] = Field(default_factory=dict)
    findings: dict[str, Any] = Field(default_factory=dict)


class NewFitVerdict(_Entity):
    """Input to `FitVerdictRepo.replace_for_run`."""

    role_model_id: UUID
    fit: str
    verdict: str
    note: str = ""
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    probe: dict[str, Any] = Field(default_factory=dict)


class NewRoleModel(_Entity):
    """Input to `RoleModelRepo.upsert`."""

    code: str
    name: str
    vision: str
    five_year_path: str
    must_accumulate: str
    cost: str
    tags: list[str] = Field(default_factory=list)
    author: str = "system"
    author_user_id: UUID | None = None


class NewMilestone(_Entity):
    """Input to `PlanTreeRepo.replace_tree`. `parent_key` names the parent by its key, so
    the whole tree can be handed over in one flat list without pre-assigned ids.
    """

    key: str
    parent_key: str | None = None
    title: str
    metric: str = ""
    target_date: date | None = None
    depth: int = 0
    position: int = 0


class NewTask(_Entity):
    """Input to `PlanTreeRepo.replace_tree`; `milestone_key` binds it to its Milestone."""

    milestone_key: str
    key: str
    week_index: int
    occurrence: int = 0
    area: str
    task_type: str
    title: str
    description: str = ""
    duration_minutes: int = 0
    sort_order: int = 0
    start_at: datetime
    end_at: datetime
    all_day: bool = False


class TaskStatusUpdate(_Entity):
    """One entry of the input to `TaskRepo.bulk_set_status`."""

    task_id: UUID
    status: str
    completed_at: datetime | None = None


class ScheduledTaskRow(_Entity):
    """A Task joined to its ScheduleSlot — what every read of a Plan's schedule returns."""

    task: Task
    slot: ScheduleSlot


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
