"""從一份基準 PlanTemplate 推導三種難度（PRD 4.3.1.1）。

LLM 只產一份基準模板，easy / hard / extremely_hard 三份由這裡的係數換算出來，
再用 trait role model 的 ``pacing`` 上下限夾住。三份共用同一個
``goal_statement`` / ``success_criteria`` / ``assumptions``。
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from packages.config import CONFIG_DIR, load_yaml_config
from services.plan_engine.domain.template import Phase, PlanTemplate, WeeklyItem

__all__ = [
    "Difficulty",
    "DifficultyCoefficients",
    "DifficultyConfig",
    "Pacing",
    "derive",
    "load_difficulty_config",
]

_MIN_DURATION_MINUTES = 5
_MAX_DURATION_MINUTES = 300
_MIN_TIMES_PER_WEEK = 1
_MAX_TIMES_PER_WEEK = 7
_DAYS_PER_WEEK = 7


class Difficulty(StrEnum):
    easy = "easy"
    hard = "hard"
    extremely_hard = "extremely_hard"


class DifficultyCoefficients(BaseModel):
    """單一難度的換算係數。"""

    model_config = ConfigDict(extra="forbid")

    frequency: float
    duration: float
    weeks: float
    title_suffix: str


class DifficultyConfig(BaseModel):
    """``config/difficulty_coefficients.yaml`` 的內容。"""

    model_config = ConfigDict(extra="forbid")

    coefficients: dict[Difficulty, DifficultyCoefficients]


class Pacing(BaseModel):
    """trait role model 的硬約束。

    Deliberate duplicate: Role Model 在 ``services/role_model/domain/content.py``
    有一份同名同欄位的定義。Service 之間禁止互相 import，兩份以 JSON 為契約
    ——契約是 ``role_models.content["pacing"]``，經 ``plan_sessions.context_snapshot``
    傳到這裡再用 ``Pacing.model_validate(dict)`` 讀回。改一邊就要改另一邊。
    """

    model_config = ConfigDict(extra="forbid")

    sessions_per_week: tuple[int, int]
    session_minutes: tuple[int, int]
    rest_days_min: int
    progression_rate: float
    missed_policy: Literal["none", "same-week", "next-day"]
    deload_every_weeks: int | None = None
    intensity_bias: Literal["low", "medium", "high"]


def load_difficulty_config(path: Path | None = None) -> DifficultyConfig:
    """讀難度係數設定，預設 ``config/difficulty_coefficients.yaml``。"""
    return load_yaml_config(path or CONFIG_DIR / "difficulty_coefficients.yaml", DifficultyConfig)


def derive(
    base: PlanTemplate,
    difficulty: Difficulty,
    config: DifficultyConfig,
    pacing: Pacing | None,
) -> PlanTemplate:
    """依係數與 pacing 推導出指定難度的模板。

    ``duration_weeks`` 的下限是 ``len(base.phases)``：每個 phase 至少要佔一週，
    phases 必須連續且覆蓋全期，週數少於 phase 數就無解，因此係數算出來太小時
    會被提到 phase 數。
    """
    coefficients = config.coefficients[difficulty]

    # 1. 週數
    weeks = max(1, round(base.duration_weeks * coefficients.weeks), len(base.phases))

    # 2. 每週項目的次數與時長
    items = [_scale_item(item, coefficients) for item in base.weekly_template]

    # 3. phases 依新週數等比例重算
    phases = _rescale_phases(base.phases, base.duration_weeks, weeks)

    # 4. pacing 夾住
    if pacing is not None:
        items = _apply_pacing(items, pacing)

    # 5–6. title 加後綴，goal_statement / success_criteria / assumptions 原樣沿用。
    # 走 model_validate 而非 model_copy，讓 PlanTemplate 的 phases 覆蓋驗證真的跑到。
    return PlanTemplate.model_validate(
        {
            **base.model_dump(),
            "title": f"{base.title}{coefficients.title_suffix}",
            "duration_weeks": weeks,
            "phases": [phase.model_dump() for phase in phases],
            "weekly_template": [item.model_dump() for item in items],
        }
    )


def _scale_item(item: WeeklyItem, coefficients: DifficultyCoefficients) -> WeeklyItem:
    times = _clamp(
        round(item.times_per_week * coefficients.frequency),
        _MIN_TIMES_PER_WEEK,
        _MAX_TIMES_PER_WEEK,
    )
    minutes = _clamp(
        round(item.duration_minutes * coefficients.duration),
        _MIN_DURATION_MINUTES,
        _MAX_DURATION_MINUTES,
    )
    return item.model_copy(update={"times_per_week": times, "duration_minutes": minutes})


def _rescale_phases(phases: list[Phase], old_weeks: int, new_weeks: int) -> list[Phase]:
    """等比例換算每個 phase 的週界，保持連續、覆蓋全期、每個至少一週。"""
    count = len(phases)
    # 每個 phase 的結束界（exclusive），等比例換算。
    bounds = [round((phase.week_end + 1) * new_weeks / old_weeks) for phase in phases]

    # 前向：至少一週，且嚴格遞增。
    previous = 0
    for index in range(count):
        bounds[index] = max(bounds[index], previous + 1)
        previous = bounds[index]

    # 後向：最後一個必須剛好蓋滿全期，前面的往回壓，仍保證每個至少一週。
    bounds[-1] = new_weeks
    for index in range(count - 2, -1, -1):
        bounds[index] = min(bounds[index], bounds[index + 1] - 1)

    rescaled: list[Phase] = []
    start = 0
    for phase, end in zip(phases, bounds, strict=True):
        rescaled.append(phase.model_copy(update={"week_start": start, "week_end": end - 1}))
        start = end
    return rescaled


def _apply_pacing(items: list[WeeklyItem], pacing: Pacing) -> list[WeeklyItem]:
    """把每項時長夾進 ``session_minutes``，再把 session 總次數夾進上下限。"""
    minutes_min, minutes_max = pacing.session_minutes
    working = [
        item.model_copy(
            update={
                "duration_minutes": _clamp(
                    item.duration_minutes,
                    max(minutes_min, _MIN_DURATION_MINUTES),
                    min(minutes_max, _MAX_DURATION_MINUTES),
                )
            }
        )
        for item in items
    ]

    sessions = [index for index, item in enumerate(working) if item.task_type == "session"]
    if not sessions:
        return working

    # 週內排程日數不得超過 7 - rest_days_min（Scheduler 會再驗一次）。
    weekly_min, weekly_max = pacing.sessions_per_week
    weekly_max = min(weekly_max, _DAYS_PER_WEEK - pacing.rest_days_min)
    weekly_min = min(weekly_min, weekly_max)

    total = sum(working[index].times_per_week for index in sessions)
    while total > weekly_max:
        # 從 times_per_week 最大的項目逐一減 1；單項不得低於 1。
        candidates = [i for i in sessions if working[i].times_per_week > _MIN_TIMES_PER_WEEK]
        if not candidates:
            break
        target = max(candidates, key=lambda i: (working[i].times_per_week, -i))
        working[target] = _bump(working[target], -1)
        total -= 1
    while total < weekly_min:
        # 反向操作：從最小的項目逐一加 1；單項不得高於 7。
        candidates = [i for i in sessions if working[i].times_per_week < _MAX_TIMES_PER_WEEK]
        if not candidates:
            break
        target = min(candidates, key=lambda i: (working[i].times_per_week, i))
        working[target] = _bump(working[target], 1)
        total += 1
    return working


def _bump(item: WeeklyItem, delta: int) -> WeeklyItem:
    return item.model_copy(update={"times_per_week": item.times_per_week + delta})


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))
