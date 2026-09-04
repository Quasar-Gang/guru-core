from datetime import UTC, date, datetime

from services.api.domain.markdown_export import (
    MarkdownOptions,
    PhaseData,
    PlanExportData,
    PlanTaskExportData,
    render_markdown,
)

TPE = "Asia/Taipei"


def _utc(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=UTC)


PLAN = PlanExportData(
    title="12 週 5K 跑進 30 分（穩健）",
    goal_statement="12 週後在同一路線 5 公里完賽時間 ≤ 30:00",
    difficulty="hard",
    duration_weeks=12,
    start_date=date(2026, 9, 8),
    deadline=date(2026, 11, 29),
    success_criteria=["第 12 週測驗 ≤ 30:00", "全程不停下步行"],
    assumptions=["目前 5K 約 38 分", "未參考既有行事曆"],
    phases=[
        PhaseData(
            index=0,
            name="基礎期",
            week_start=0,
            week_end=3,
            focus="建立跑量",
            milestone_title="連續慢跑 5K 不停",
            milestone_metric="完成即可，不計時",
        ),
        PhaseData(
            index=1,
            name="強化期",
            week_start=4,
            week_end=11,
            focus="加入間歇",
            milestone_title="5K 測驗",
            milestone_metric="≤ 30:00",
        ),
    ],
)

# 2026-09-08 19:30 Asia/Taipei == 2026-09-08 11:30 UTC
TASKS = [
    PlanTaskExportData(
        week_index=0,
        title="輕鬆跑",
        description="可以邊跑邊講話的配速",
        start_at=_utc(2026, 9, 8, 11, 30),
        end_at=_utc(2026, 9, 8, 12, 0),
        status="done",
        sort_order=0,
    ),
    PlanTaskExportData(
        week_index=0,
        title="間歇跑",
        description="熱身 10 分，6 × 400m",
        start_at=_utc(2026, 9, 10, 11, 30),
        end_at=_utc(2026, 9, 10, 12, 5),
        status="pending",
        sort_order=1,
    ),
    PlanTaskExportData(
        week_index=0,
        title="長距離慢跑",
        start_at=_utc(2026, 9, 11, 23, 0),
        end_at=_utc(2026, 9, 11, 23, 45),
        status="missed",
        sort_order=2,
    ),
    PlanTaskExportData(
        week_index=0,
        title="伸展 10 分",
        start_at=_utc(2026, 9, 12, 13, 30),
        end_at=_utc(2026, 9, 12, 13, 40),
        status="skipped",
        sort_order=3,
    ),
    PlanTaskExportData(
        week_index=3,
        title="連續慢跑 5K 不停",
        start_at=_utc(2026, 9, 27, 16, 0),
        end_at=_utc(2026, 9, 28, 16, 0),
        all_day=True,
        status="pending",
        sort_order=4,
    ),
]


def _render(options: MarkdownOptions | None = None, tz: str = TPE) -> str:
    return render_markdown(PLAN, TASKS, options or MarkdownOptions(), tz)


def test_document_starts_with_the_plan_title():
    assert _render().splitlines()[0] == "# 12 週 5K 跑進 30 分（穩健）"


def test_period_line_matches_the_prd_shape():
    assert "**期程**：2026-09-08 – 2026-11-29（12 週）　**難度**：hard" in _render()


def test_criteria_and_assumption_sections_are_present():
    out = _render()
    assert "## 達成標準" in out
    assert "- 第 12 週測驗 ≤ 30:00" in out
    assert "## 系統假設" in out
    assert "- 未參考既有行事曆" in out


def test_phase_table_has_a_row_per_phase():
    out = _render()
    assert "| 階段 | 週次 | 重點 | 里程碑 |" in out
    assert "| 基礎期 | W1–W4 | 建立跑量 | 連續慢跑 5K 不停 |" in out
    assert "| 強化期 | W5–W12 | 加入間歇 | 5K 測驗 |" in out


def test_week_heading_carries_the_date_span_and_phase():
    assert "### 第 1 週（09/08 – 09/14）　基礎期" in _render()


def test_done_task_uses_a_checked_box():
    assert "- [x] 09/08 (二) 19:30–20:00　輕鬆跑 — 可以邊跑邊講話的配速" in _render()


def test_pending_task_uses_an_empty_box():
    assert "- [ ] 09/10 (四) 19:30–20:05　間歇跑 — 熱身 10 分，6 × 400m" in _render()


def test_missed_task_is_struck_through_and_marked():
    assert "- [ ] ~~09/12 (六) 07:00–07:45　長距離慢跑~~ ✗ 未達標" in _render()


def test_skipped_task_is_labelled():
    assert "- [ ] 09/12 (六) 21:30–21:40　伸展 10 分 — 略過" in _render()


def test_all_day_task_shows_the_whole_day():
    assert "- [ ] 09/28 (一) 全天　連續慢跑 5K 不停" in _render()


def test_progress_line_counts_every_status():
    assert "完成 1 / 5（20%）　未達標 1　略過 1" in _render()


def test_include_completed_false_drops_done_tasks():
    out = _render(MarkdownOptions(include_completed=False))
    assert "輕鬆跑" not in out
    assert "間歇跑" in out
    # the progress line always reflects the whole plan, not the slice
    assert "完成 1 / 5（20%）" in out


def test_from_and_to_filter_by_local_day():
    out = _render(MarkdownOptions(from_=date(2026, 9, 10), to=date(2026, 9, 11)))
    assert "間歇跑" in out
    assert "輕鬆跑" not in out
    assert "長距離慢跑" not in out


def test_timezone_changes_the_rendered_clock():
    assert _render(tz="UTC") != _render(tz=TPE)
    assert "- [x] 09/08 (二) 11:30–12:00　輕鬆跑" in _render(tz="UTC")


def test_empty_plan_still_renders_headings():
    out = render_markdown(PLAN, [], MarkdownOptions(), TPE)
    assert "## 週計畫" in out
    assert "完成 0 / 0（0%）　未達標 0　略過 0" in out
