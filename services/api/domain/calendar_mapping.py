"""Schedule slot -> Google Calendar event mapping.

Pure functions: no IO, no repository, no calendar client. `PushExport` walks the schedule
and hands each draft to the `CalendarPort`.

The draft type is deliberately domain-local: `CalendarEventWrite` lives in the application
layer, which the domain must not import. `PushExport` turns a draft into the port's type.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from packages.config import CONFIG_DIR, load_yaml_config
from packages.repo.entities import ScheduledTaskRow

__all__ = [
    "COLOR_CONFIG_FILENAME",
    "CalendarEventDraft",
    "ColorMap",
    "load_color_map",
    "should_export",
    "to_calendar_event",
]

COLOR_CONFIG_FILENAME = "calendar_colors.yaml"

#: Rest days clutter a calendar, so they stay out of the export.
REST_TASK_TYPE = "rest"

_STATUS_DONE = "done"
_STATUS_MISSED = "missed"

#: Prefixed onto the summary so the calendar itself shows what happened.
_DONE_PREFIX = "[x] "
_MISSED_PREFIX = "[ ] "


class ColorMap(BaseModel):
    """`colorId` per task kind: same kind, same colour."""

    model_config = ConfigDict(frozen=True)

    default: str
    by_key: dict[str, str] = Field(default_factory=dict)
    by_task_type: dict[str, str] = Field(default_factory=dict)

    def color_for(self, key: str, task_type: str) -> str:
        """The most specific mapping wins: task key, then task type, then the default."""
        by_key = self.by_key.get(key)
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


def should_export(row: ScheduledTaskRow) -> bool:
    """Rest markers stay out; everything else the plan asks for goes in."""
    return row.task.task_type != REST_TASK_TYPE


def to_calendar_event(
    row: ScheduledTaskRow, colors: ColorMap, plan_title: str
) -> CalendarEventDraft:
    """Turn one scheduled task into an event, carrying its identity in private props.

    The private props are what make a second push an update rather than a duplicate: the
    task id travels with the event and comes back on the next read.
    """
    return CalendarEventDraft(
        summary=f"{_prefix(row.task.status)}{row.task.title}",
        description=_description(row, plan_title),
        start_at=row.slot.start_at,
        end_at=row.slot.end_at,
        all_day=row.slot.all_day,
        color_id=colors.color_for(row.task.key, row.task.task_type),
        private_props={"guru_task_id": str(row.task.id), "guru_plan_id": str(row.task.plan_id)},
    )


def _prefix(status: str) -> str:
    if status == _STATUS_DONE:
        return _DONE_PREFIX
    if status == _STATUS_MISSED:
        return _MISSED_PREFIX
    return ""


def _description(row: ScheduledTaskRow, plan_title: str) -> str:
    lines = [row.task.description] if row.task.description else []
    lines.append(f"From the guru plan: {plan_title}")
    return "\n\n".join(lines)
