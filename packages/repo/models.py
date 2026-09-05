"""SQLAlchemy ORM models — the single PostgreSQL schema shared by every service.

The first line of each model docstring names the owning service: only that service may
write to the table, everyone else reads it.

The schema follows the three stations. Station 1 turns uploads into a Profile, Reports and
six Fit Verdicts, and settles into an append-only Direction Hypothesis. Station 2 turns one
Hypothesis into a Plan: a Milestone tree, flat Tasks, and the Schedule Slots those Tasks
project onto. Station 3 reconciles what was done against what the Hypothesis predicted.

Two structural rules are enforced here rather than merely documented:

* ``tasks.milestone_id`` is ``NOT NULL`` and there is no ``tasks.parent_id`` — Milestones
  nest, Tasks never do, so "done" always means the same thing.
* ``direction_hypotheses`` is unique on ``(user_id, version)`` and no repository exposes an
  update — a hypothesis you can quietly edit can never be falsified.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _updated_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


def _user_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )


# --- Identity and intake -----------------------------------------------------


class User(Base):
    """Owner: API Service."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _pk()
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    google_sub: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    created_at: Mapped[datetime] = _created_at()


class OAuthConnection(Base):
    """Owner: API Service."""

    __tablename__ = "oauth_connections"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_oauth_user_provider"),)

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    encrypted_refresh_token: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    scopes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class Import(Base):
    """Owner: API Service. One upload of personal data."""

    __tablename__ = "imports"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    filename: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class Document(Base):
    """Owner: API Service. The Uploader's normalized read of one Import."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _pk()
    import_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("imports.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    events: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    text_chunks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = _created_at()


class Profile(Base):
    """Owner: Engine. What the personal data adds up to — exactly one row per user.

    Revised in place, never duplicated: the user_id *is* the primary key, so a second
    Profile cannot be written even by mistake.
    """

    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    signals: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    coverage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source_import_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    updated_at: Mapped[datetime] = _updated_at()


# --- Station 1: analysis and direction ---------------------------------------


class DirectionRun(Base):
    """Owner: API Service creates rows; the Engine owns the state transitions.

    One pass of steps 3-8a: analyze the Profile into Reports, then score every Role Model
    into a Fit Verdict. Reports and Fit Verdicts carry the run id, so a re-run never mixes
    its evidence with the previous one's.
    """

    __tablename__ = "direction_runs"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    readouts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class Report(Base):
    """Owner: Engine. The Analyzer's read of the Profile along one dimension."""

    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("run_id", "dimension", name="uq_report_run_dimension"),
        Index("ix_reports_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("direction_runs.id", ondelete="CASCADE"), nullable=False
    )
    dimension: Mapped[str] = mapped_column(String(16), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    findings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = _created_at()


class RoleModel(Base):
    """Owner: Catalog Service. A borrowed life shape, identical for every user.

    ``cost`` is NOT NULL because a template with no stated trade-off turns the catalogue
    into a popularity contest. Everything computed per user lives on the Fit Verdict.
    """

    __tablename__ = "role_models"
    __table_args__ = (
        UniqueConstraint("code", name="uq_role_model_code"),
        Index("ix_role_models_tags", "tags", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = _pk()
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    vision: Mapped[str] = mapped_column(Text, nullable=False)
    five_year_path: Mapped[str] = mapped_column(Text, nullable=False)
    must_accumulate: Mapped[str] = mapped_column(Text, nullable=False)
    cost: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    author: Mapped[str] = mapped_column(String(16), nullable=False, default="system")
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class FitVerdict(Base):
    """Owner: Engine. One Role Model held against one user's evidence.

    ``evidence`` carries exactly five items, each ``for`` or ``against`` and each citing a
    Report; ``probe`` is the single cheap experiment with its own stated cost. Both shapes
    are validated before the row is written — an uncited claim is not evidence.
    """

    __tablename__ = "fit_verdicts"
    __table_args__ = (UniqueConstraint("run_id", "role_model_id", name="uq_verdict_run_model"),)

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("direction_runs.id", ondelete="CASCADE"), nullable=False
    )
    role_model_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("role_models.id", ondelete="CASCADE"), nullable=False
    )
    fit: Mapped[str] = mapped_column(String(24), nullable=False)
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    probe: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = _created_at()


class QuestionAnswer(Base):
    """Owner: API Service. One of the three constraint questions; always skippable."""

    __tablename__ = "question_answers"
    __table_args__ = (UniqueConstraint("user_id", "question_key", name="uq_answer_user_question"),)

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    question_key: Mapped[str] = mapped_column(String(8), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    skipped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    answered_at: Mapped[datetime] = _created_at()


class Quota(Base):
    """Owner: API Service. What Q-3 declared the Schedule may spend, and what gets cut first.

    Distinct from capacity: capacity is observed and says what is physically possible; the
    quota is declared and says what the user has agreed to allow.
    """

    __tablename__ = "quotas"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    drop_first: Mapped[str] = mapped_column(String(16), nullable=False)
    weekly_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    updated_at: Mapped[datetime] = _updated_at()


class DirectionHypothesis(Base):
    """Owner: API Service. Append-only: no repository or route exposes an update.

    Unique on ``(user_id, version)``. A quarter later the system raises v0 unprompted and
    asks whether the shape still counts; that only works if v0 still says what it said.
    """

    __tablename__ = "direction_hypotheses"
    __table_args__ = (UniqueConstraint("user_id", "version", name="uq_hypothesis_user_version"),)

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    role_model_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("role_models.id", ondelete="RESTRICT"), nullable=False
    )
    fit_verdict_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("fit_verdicts.id", ondelete="RESTRICT"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    drop_first: Mapped[str | None] = mapped_column(String(16))
    answers_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = _created_at()


# --- Station 2: the plan -----------------------------------------------------


class Plan(Base):
    """Owner: API Service creates the row with the Hypothesis; the Engine fills it in.

    Exactly one Plan per Hypothesis — no difficulty variants. The row exists from the moment
    the Hypothesis does, in status ``generating``, so the client has something to poll.
    """

    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    hypothesis_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("direction_hypotheses.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    title: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="generating")
    #: Set by the Engine when it generates, not by the API when it creates: the rule for
    #: where a plan starts is scheduling policy, and lives in one place only.
    start_date: Mapped[date | None] = mapped_column(Date)
    duration_weeks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    structure: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class Milestone(Base):
    """Owner: Engine. A checkpoint. ``parent_id`` is nullable, so Milestones form a tree."""

    __tablename__ = "milestones"
    __table_args__ = (
        UniqueConstraint("plan_id", "key", name="uq_milestone_plan_key"),
        Index("ix_milestones_plan_parent", "plan_id", "parent_id"),
    )

    id: Mapped[uuid.UUID] = _pk()
    plan_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("milestones.id", ondelete="CASCADE")
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    metric: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_date: Mapped[date | None] = mapped_column(Date)
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")


class Task(Base):
    """Owner: Engine creates rows; the API Service writes completion.

    ``milestone_id`` is NOT NULL and there is no ``parent_id``: a Task never contains a
    Task. Anything needing further breakdown is a sub-Milestone. Times live on
    ``schedule_slots`` — a Task is relative, the Schedule is its projection onto real dates.
    """

    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("plan_id", "key", "week_index", "occurrence", name="uq_task_key"),
        Index("ix_tasks_milestone", "milestone_id"),
    )

    id: Mapped[uuid.UUID] = _pk()
    plan_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    milestone_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("milestones.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    week_index: Mapped[int] = mapped_column(Integer, nullable=False)
    occurrence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    area: Mapped[str] = mapped_column(String(16), nullable=False)
    task_type: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ScheduleSlot(Base):
    """Owner: Engine places rows; the API Service writes the export columns.

    One slot per Task, and deterministic given the template, start date, capacity, busy
    blocks and quota. Kept apart from ``tasks`` so the Schedule can be recomputed without
    touching what the Plan says, which is what makes Station 3's comparison honest.
    """

    __tablename__ = "schedule_slots"
    __table_args__ = (Index("ix_slots_plan_start", "plan_id", "start_at"),)

    id: Mapped[uuid.UUID] = _pk()
    plan_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    all_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    external_ref: Mapped[str | None] = mapped_column(String(256))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Checkin(Base):
    """Owner: API Service. What was actually done on one day."""

    __tablename__ = "checkins"
    __table_args__ = (UniqueConstraint("plan_id", "checkin_date", name="uq_checkin_plan_date"),)

    id: Mapped[uuid.UUID] = _pk()
    plan_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    checkin_date: Mapped[date] = mapped_column(Date, nullable=False)
    task_results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class PlanExport(Base):
    """Owner: API Service. The Schedule pushed out to a calendar the user already reads."""

    __tablename__ = "plan_exports"
    __table_args__ = (UniqueConstraint("plan_id", "target", name="uq_export_plan_target"),)

    id: Mapped[uuid.UUID] = _pk()
    plan_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    target: Mapped[str] = mapped_column(String(32), nullable=False)
    external_calendar_id: Mapped[str | None] = mapped_column(String(256))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


# --- Station 3: reconciliation -----------------------------------------------


class Reconciliation(Base):
    """Owner: API Service creates the row; the Engine fills the comparison and the note.

    The output is a question, not a score: ``comparison`` is computed in code and only then
    narrated, and ``revision_kind`` classifies a changed plan against the user's own Q-2
    baseline rather than punishing it.
    """

    __tablename__ = "reconciliations"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    hypothesis_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("direction_hypotheses.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    comparison: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    narrative: Mapped[str] = mapped_column(Text, nullable=False, default="")
    outcome: Mapped[str | None] = mapped_column(String(16))
    revision_kind: Mapped[str | None] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


# --- Cross-cutting -----------------------------------------------------------


class LlmCall(Base):
    """Owner: every service. Append-only; rows are never updated."""

    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = _pk()
    prompt_name: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    job_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created_at()
