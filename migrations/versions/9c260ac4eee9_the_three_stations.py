"""The three stations: intake, direction, the plan, and the quarterly review.

The initial schema. `guru-core` had exactly one migration before this and no production
data depended on it, so the whole thing is squashed here rather than evolved through a long
chain of renames for a domain that was replaced rather than adjusted.

Revision ID: 9c260ac4eee9
Revises:
Create Date: 2026-09-06 02:06:28.607809
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9c260ac4eee9"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("prompt_name", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("degraded", sa.Boolean(), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("google_sub", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("google_sub"),
    )
    op.create_table(
        "direction_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("readouts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "imports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "oauth_connections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("encrypted_refresh_token", sa.LargeBinary(), nullable=False),
        sa.Column("scopes", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "provider", name="uq_oauth_user_provider"),
    )
    op.create_table(
        "profiles",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("signals", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("coverage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_import_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "question_answers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("question_key", sa.String(length=8), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("skipped", sa.Boolean(), nullable=False),
        sa.Column(
            "answered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "question_key", name="uq_answer_user_question"),
    )
    op.create_table(
        "quotas",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("drop_first", sa.String(length=16), nullable=False),
        sa.Column("weekly_minutes", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "role_models",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("vision", sa.Text(), nullable=False),
        sa.Column("five_year_path", sa.Text(), nullable=False),
        sa.Column("must_accumulate", sa.Text(), nullable=False),
        sa.Column("cost", sa.Text(), nullable=False),
        sa.Column("tags", sa.ARRAY(sa.String()), nullable=False),
        sa.Column("author", sa.String(length=16), nullable=False),
        sa.Column("author_user_id", sa.UUID(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_role_model_code"),
    )
    op.create_index(
        "ix_role_models_tags", "role_models", ["tags"], unique=False, postgresql_using="gin"
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("import_id", sa.UUID(), nullable=False),
        sa.Column("events", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("text_chunks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["import_id"], ["imports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("import_id"),
    )
    op.create_table(
        "fit_verdicts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("role_model_id", sa.UUID(), nullable=False),
        sa.Column("fit", sa.String(length=24), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("probe", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["role_model_id"], ["role_models.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["direction_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "role_model_id", name="uq_verdict_run_model"),
    )
    op.create_table(
        "reports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("dimension", sa.String(length=16), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("findings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["direction_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "dimension", name="uq_report_run_dimension"),
    )
    op.create_index("ix_reports_user", "reports", ["user_id"], unique=False)
    op.create_table(
        "direction_hypotheses",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("role_model_id", sa.UUID(), nullable=False),
        sa.Column("fit_verdict_id", sa.UUID(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("evidence_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("drop_first", sa.String(length=16), nullable=True),
        sa.Column("answers_count", sa.Integer(), nullable=False),
        sa.Column("review_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["fit_verdict_id"], ["fit_verdicts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["role_model_id"], ["role_models.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "version", name="uq_hypothesis_user_version"),
    )
    op.create_table(
        "plans",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("hypothesis_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("duration_weeks", sa.Integer(), nullable=False),
        sa.Column("structure", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["hypothesis_id"], ["direction_hypotheses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hypothesis_id"),
    )
    op.create_table(
        "reconciliations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("hypothesis_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("comparison", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=True),
        sa.Column("revision_kind", sa.String(length=16), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["hypothesis_id"], ["direction_hypotheses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "checkins",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("checkin_date", sa.Date(), nullable=False),
        sa.Column("task_results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "checkin_date", name="uq_checkin_plan_date"),
    )
    op.create_table(
        "milestones",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["milestones.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "key", name="uq_milestone_plan_key"),
    )
    op.create_index(
        "ix_milestones_plan_parent", "milestones", ["plan_id", "parent_id"], unique=False
    )
    op.create_table(
        "plan_exports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("target", sa.String(length=32), nullable=False),
        sa.Column("external_calendar_id", sa.String(length=256), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "target", name="uq_export_plan_target"),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("milestone_id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("week_index", sa.Integer(), nullable=False),
        sa.Column("occurrence", sa.Integer(), nullable=False),
        sa.Column("area", sa.String(length=16), nullable=False),
        sa.Column("task_type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["milestone_id"], ["milestones.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "key", "week_index", "occurrence", name="uq_task_key"),
    )
    op.create_index("ix_tasks_milestone", "tasks", ["milestone_id"], unique=False)
    op.create_table(
        "schedule_slots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("all_day", sa.Boolean(), nullable=False),
        sa.Column("external_ref", sa.String(length=256), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
    )
    op.create_index("ix_slots_plan_start", "schedule_slots", ["plan_id", "start_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_slots_plan_start", table_name="schedule_slots")
    op.drop_table("schedule_slots")
    op.drop_index("ix_tasks_milestone", table_name="tasks")
    op.drop_table("tasks")
    op.drop_table("plan_exports")
    op.drop_index("ix_milestones_plan_parent", table_name="milestones")
    op.drop_table("milestones")
    op.drop_table("checkins")
    op.drop_table("reconciliations")
    op.drop_table("plans")
    op.drop_table("direction_hypotheses")
    op.drop_index("ix_reports_user", table_name="reports")
    op.drop_table("reports")
    op.drop_table("fit_verdicts")
    op.drop_table("documents")
    op.drop_index("ix_role_models_tags", table_name="role_models", postgresql_using="gin")
    op.drop_table("role_models")
    op.drop_table("quotas")
    op.drop_table("question_answers")
    op.drop_table("profiles")
    op.drop_table("oauth_connections")
    op.drop_table("imports")
    op.drop_table("direction_runs")
    op.drop_table("users")
    op.drop_table("llm_calls")
