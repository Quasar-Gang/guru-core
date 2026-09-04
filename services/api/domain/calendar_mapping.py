"""Plan task -> Google Calendar event mapping (PRD 4.3.4).

Pure functions: no IO, no repository, no calendar client. `PushExport` walks the tasks and
hands each draft to the `CalendarPort`.

The draft type is deliberately domain-local: `CalendarEventWrite` lives in the application
layer, which the domain must not import. `PushExport` turns a draft into the port's type.

The provenance line and the check / cross prefixes are user-facing product strings fixed by
PRD 4.3.4, so they stay in Traditional Chinese while the rest of the codebase is English.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from packages.config import CONFIG_DIR, load_yaml_config
from packages.repo.entities import PlanTask

__all__ = [
    "COLOR_CONFIG_FILENAME",
    "CalendarEventDraft",
    "ColorMap",
    "load_color_map",
    "should_export",
    "to_calendar_event",
]

COLOR_CONFIG_FILENAME = "calendar_colors.yaml"

#: Rest days clutter a calendar, so they stay out unless the user asks for them (PRD 4.3.4).
REST_TASK_TYPE = "rest"

_STATUS_DONE = "done"
_STATUS_MISSED = "missed"


class ColorMap(BaseModel):
    """`colorId` per task kind: same kind, same color (PRD 4.3.4)."""

    model_config = ConfigDict(frozen=True)

    default: str
    by_template_key: dict[str, str] = Field(default_factory=dict)
    by_task_type: dict[str, str] = Field(default_factory=dict)

    def color_for(self, template_key: str, task_type: str) -> str:
        """The most specific mapping wins: template key, then task type, then the default."""
        by_key = self.by_template_key.get(template_key)
        if by_key is not None:
            return by_key
        return self.by_task_type.get(task_type, self.default)


class CalendarEventDraft(BaseModel):
    """One calendar event, described without reference to any calendar provider."""

    model_config = ConfigDict(frozen=True)

    summary: str
    description: str
    start_at: datetime
    end_at: datetime
    all_day: bool
    color_id: str
    private_props: dict[str, str] = Field(default_factory=dict)


def load_color_map(path: Path | None = None) -> ColorMap:
    return load_yaml_config(path or CONFIG_DIR / COLOR_CONFIG_FILENAME, ColorMap)


def should_export(task: PlanTask, include_rest: bool) -> bool:
    return include_rest or task.task_type != REST_TASK_TYPE


def to_calendar_event(task: PlanTask, plan_title: str, color_map: ColorMap) -> CalendarEventDraft:
    """`all_day` is passed through; turning it into a date or a dateTime is the adapter's job."""
    return CalendarEventDraft(
        summary=_summary(task),
        description=_description(task, plan_title),
        start_at=task.start_at,
        end_at=task.end_at,
        all_day=task.all_day,
        color_id=color_map.color_for(task.template_key, task.task_type),
        private_props={"guru_task_id": str(task.id), "guru_plan_id": str(task.plan_id)},
    )


def _summary(task: PlanTask) -> str:
    """Check-in outcomes show up as a prefix, so the calendar mirrors what the app knows."""
    if task.status == _STATUS_DONE:
        return f"✓ {task.title}"
    if task.status == _STATUS_MISSED:
        return f"✗ {task.title}"
    return task.title


def _description(task: PlanTask, plan_title: str) -> str:
    provenance = f"來自 guru-core · {plan_title} · 第 {task.week_index + 1} 週"
    return f"{task.description}\n\n{provenance}" if task.description else provenance
