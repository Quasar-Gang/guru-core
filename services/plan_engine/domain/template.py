"""PlanTemplate 與其子型別（PRD 4.3.1）。難度不在 template 內。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DayHint = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun", "any", "weekend", "weekday"]
SlotHint = Literal["morning", "noon", "evening", "any"]
TaskType = Literal["session", "habit", "checkpoint", "rest"]


class Milestone(BaseModel):
    """階段結束的檢核點，scheduler 會展開成一個 checkpoint task。"""

    title: str
    metric: str


class Phase(BaseModel):
    """計畫的一個階段，週次為相對週（從 0 起）。"""

    index: int
    name: str
    week_start: int = Field(ge=0)
    week_end: int = Field(ge=0)
    focus: str
    milestone: Milestone


class WeeklyItem(BaseModel):
    """一週骨架中的一項任務，scheduler 用它展開成每週任務。"""

    key: str = Field(pattern=r"^[a-z0-9_]+$")
    title: str
    task_type: TaskType
    day_hint: DayHint
    slot_hint: SlotHint
    duration_minutes: int = Field(ge=5, le=300)
    description: str = ""
    times_per_week: int = Field(default=1, ge=1, le=7)


class PlanTemplate(BaseModel):
    """LLM 產出的基準計畫模板；difficulty 由程式在外層推導。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=40)
    goal_statement: str
    duration_weeks: int = Field(ge=1, le=104)
    assumptions: list[str] = []
    success_criteria: list[str] = Field(min_length=1)
    phases: list[Phase] = Field(min_length=1, max_length=6)
    weekly_template: list[WeeklyItem] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def phases_cover_duration(self) -> PlanTemplate:
        for position, phase in enumerate(self.phases):
            if phase.index != position:
                raise ValueError(f"phases[{position}].index must be {position}, got {phase.index}")
            if phase.week_start > phase.week_end:
                raise ValueError(
                    f"phases[{position}] week_start {phase.week_start} "
                    f"must be <= week_end {phase.week_end}"
                )
            if position == 0:
                if phase.week_start != 0:
                    raise ValueError(f"phases[0].week_start must be 0, got {phase.week_start}")
            else:
                previous_end = self.phases[position - 1].week_end
                if phase.week_start != previous_end + 1:
                    raise ValueError(
                        f"phases[{position}].week_start must be {previous_end + 1} "
                        f"to stay contiguous, got {phase.week_start}"
                    )
        last_week_end = self.phases[-1].week_end
        if last_week_end != self.duration_weeks - 1:
            raise ValueError(
                f"last phase week_end must be {self.duration_weeks - 1} "
                f"to cover duration_weeks, got {last_week_end}"
            )
        return self


class PlanTemplateOutput(BaseModel):
    """generate_plans 的 LLM output_schema wrapper。"""

    template: PlanTemplate
