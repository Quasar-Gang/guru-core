"""Markdown rendering for a plan (PRD 4.3.5).

Pure functions: no IO, no repository, no storage. The use case reads the plan
and its tasks, calls `render_markdown`, and stores the result.

The section headings and task-line shapes below are the product's user-facing
output, fixed by PRD 4.3.5, so they stay in Traditional Chinese while the rest
of the codebase is English.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

_WEEKDAY_NAMES = ("一", "二", "三", "四", "五", "六", "日")

_STATUS_DONE = "done"
_STATUS_MISSED = "missed"
_STATUS_SKIPPED = "skipped"


class MarkdownOptions(BaseModel):
    """Caller-controlled slicing of the export."""

    model_config = ConfigDict(frozen=True)

    include_completed: bool = True
    from_: date | None = None
    to: date | None = None


class PhaseData(BaseModel):
    """One phase of `plans.structure["phases"]`."""

    index: int
    name: str
    week_start: int
    week_end: int
    focus: str = ""
    milestone_title: str = ""
    milestone_metric: str = ""

    @classmethod
    def from_structure(cls, raw: dict[str, Any]) -> PhaseData:
        milestone = raw.get("milestone") or {}
        return cls(
            index=int(raw["index"]),
            name=str(raw["name"]),
            week_start=int(raw["week_start"]),
            week_end=int(raw["week_end"]),
            focus=str(raw.get("focus", "")),
            milestone_title=str(milestone.get("title", "")),
            milestone_metric=str(milestone.get("metric", "")),
        )


class PlanExportData(BaseModel):
    """Everything `render_markdown` needs from the `plans` row."""

    title: str
    goal_statement: str
    difficulty: str
    duration_weeks: int
    start_date: date
    deadline: date
    success_criteria: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    phases: list[PhaseData] = Field(default_factory=list)


class PlanTaskExportData(BaseModel):
    """Everything `render_markdown` needs from one `plan_tasks` row."""

    week_index: int
    title: str
    description: str = ""
    start_at: datetime
    end_at: datetime
    all_day: bool = False
    status: str = "pending"
    sort_order: int = 0


def render_markdown(
    plan: PlanExportData,
    tasks: list[PlanTaskExportData],
    options: MarkdownOptions,
    timezone: str,
) -> str:
    """Render one plan as a single GFM document."""
    tz = ZoneInfo(timezone)
    selected = _select(tasks, options, tz)

    lines: list[str] = [
        f"# {plan.title}",
        "",
        plan.goal_statement,
        "",
        f"**期程**：{plan.start_date} – {plan.deadline}"
        f"（{plan.duration_weeks} 週）　**難度**：{plan.difficulty}",
    ]

    if plan.success_criteria:
        lines += ["", "## 達成標準", ""]
        lines += [f"- {c}" for c in plan.success_criteria]

    if plan.assumptions:
        lines += ["", "## 系統假設", ""]
        lines += [f"- {a}" for a in plan.assumptions]

    if plan.phases:
        lines += ["", "## 階段", "", "| 階段 | 週次 | 重點 | 里程碑 |", "|---|---|---|---|"]
        for phase in plan.phases:
            weeks = f"W{phase.week_start + 1}–W{phase.week_end + 1}"
            lines.append(f"| {phase.name} | {weeks} | {phase.focus} | {phase.milestone_title} |")

    lines += ["", "## 週計畫"]
    for week_index in sorted({t.week_index for t in selected}):
        week_tasks = sorted(
            (t for t in selected if t.week_index == week_index),
            key=lambda t: (t.start_at, t.sort_order),
        )
        lines += ["", _week_heading(plan, week_index, tz), ""]
        lines += [_task_line(t, tz) for t in week_tasks]

    lines += ["", "## 進度", "", _progress_line(tasks)]
    return "\n".join(lines) + "\n"


def _select(
    tasks: list[PlanTaskExportData], options: MarkdownOptions, tz: ZoneInfo
) -> list[PlanTaskExportData]:
    kept = []
    for task in tasks:
        if not options.include_completed and task.status == _STATUS_DONE:
            continue
        local_day = task.start_at.astimezone(tz).date()
        if options.from_ is not None and local_day < options.from_:
            continue
        if options.to is not None and local_day > options.to:
            continue
        kept.append(task)
    return kept


def _week_heading(plan: PlanExportData, week_index: int, tz: ZoneInfo) -> str:
    from datetime import timedelta

    week_start = plan.start_date + timedelta(weeks=week_index)
    week_end = week_start + timedelta(days=6)
    phase_name = next(
        (p.name for p in plan.phases if p.week_start <= week_index <= p.week_end),
        "",
    )
    span = f"{week_start:%m/%d} – {week_end:%m/%d}"
    heading = f"### 第 {week_index + 1} 週（{span}）"
    return f"{heading}　{phase_name}" if phase_name else heading


def _task_line(task: PlanTaskExportData, tz: ZoneInfo) -> str:
    when = _when(task, tz)
    body = f"{when}　{task.title}"
    if task.status == _STATUS_DONE:
        return f"- [x] {body}{_suffix(task)}"
    if task.status == _STATUS_MISSED:
        return f"- [ ] ~~{body}~~ ✗ 未達標"
    if task.status == _STATUS_SKIPPED:
        return f"- [ ] {body} — 略過"
    return f"- [ ] {body}{_suffix(task)}"


def _suffix(task: PlanTaskExportData) -> str:
    return f" — {task.description}" if task.description else ""


def _when(task: PlanTaskExportData, tz: ZoneInfo) -> str:
    start = task.start_at.astimezone(tz)
    weekday = _WEEKDAY_NAMES[start.weekday()]
    day = f"{start:%m/%d} ({weekday})"
    if task.all_day:
        return f"{day} 全天"
    end = task.end_at.astimezone(tz)
    return f"{day} {start:%H:%M}–{end:%H:%M}"


def _progress_line(tasks: list[PlanTaskExportData]) -> str:
    done = sum(1 for t in tasks if t.status == _STATUS_DONE)
    missed = sum(1 for t in tasks if t.status == _STATUS_MISSED)
    skipped = sum(1 for t in tasks if t.status == _STATUS_SKIPPED)
    total = len(tasks)
    pct = round(done / total * 100) if total else 0
    return f"完成 {done} / {total}（{pct}%）　未達標 {missed}　略過 {skipped}"
