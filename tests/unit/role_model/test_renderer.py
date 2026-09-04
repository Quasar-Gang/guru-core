"""Role model context rendering for the Plan Engine (PRD 12.6)."""

from packages.llm import Purpose
from services.role_model.domain import (
    NullRoleModelRenderer,
    RoleModelRenderer,
    estimate_tokens,
)

# PRD 14.2 — T2 steady-progress trait
T2_CONTENT = {
    "summary": "Fixed cadence, linear progression: go slower if needed, but move every week.",
    "pacing": {
        "sessions_per_week": [4, 5],
        "session_minutes": [30, 60],
        "rest_days_min": 1,
        "progression_rate": 0.10,
        "missed_policy": "same-week",
        "deload_every_weeks": None,
        "intensity_bias": "medium",
    },
    "provenance": {
        "sources": [],
        "confidence": "medium",
        "author": "guru team",
        "notes": "an execution style defined by the team, not a specific person",
    },
}

# PRD 14.2 — P2 Eliud Kipchoge persona
P2_CONTENT = {
    "summary": "八成訓練量放在輕鬆配速，靠週期化與每週一次長距離累積耐力。",
    "sections": {
        "principles": [
            "八成的訓練量以能邊跑邊講話的輕鬆配速進行。",
            "每週只安排一到兩次高強度課表，其餘全是輕鬆跑。",
            "訓練量以週為單位漸進，每次增量不超過前一週的一成。",
            "恢復與睡眠視為訓練的一部分，不是有空才做。",
        ],
        "weekly_structure": (
            "一週五次：三次輕鬆跑（30–50 分）、一次強度課（間歇或節奏跑）、"
            "一次長距離慢跑（週末，時間逐週延長）。其餘兩天完全休息或輕度伸展。"
        ),
        "progress_metrics": [
            "同一配速下的心率逐週下降",
            "長距離跑的持續時間逐週增加",
            "每四週一次固定距離計時，比較完成時間",
        ],
        "pitfalls": [
            "輕鬆跑跑太快，導致沒有真正的恢復日",
            "週跑量增加過快造成脛骨或膝蓋疼痛",
            "只練長距離、忽略強度課，配速停滯",
        ],
        "applicability": {
            "good_for": ["想首馬完賽者", "想突破 5K/10K 個人紀錄者", "每週能跑四次以上者"],
            "not_for": ["有未癒合下肢傷勢者", "每週只能運動兩次者", "主要目標是增肌者"],
        },
        "example_milestones": [
            "第 4 週：能連續慢跑 45 分鐘不停",
            "第 8 週：完成一次 12 公里長距離",
            "第 12 週：5 公里計時較起始成績進步 8% 以上",
        ],
    },
    "provenance": {
        "sources": [],
        "confidence": "medium",
        "author": "guru team",
        "notes": "publicly verifiable training principles only; no biography or private details",
    },
}


def test_estimate_tokens_is_half_the_character_count():
    assert estimate_tokens("abcd") == 2
    assert estimate_tokens("") == 0


def test_generate_purpose_renders_full_pacing_sentence():
    out = RoleModelRenderer().to_context(
        "trait", "steady progress", T2_CONTENT, Purpose.generate, 600
    )

    assert out.strip().endswith(
        "節奏約束：每週 4–5 次，每次 30–60 分鐘，至少休息 1 天；"
        "每兩週增量不超過 10%；漏做的任務在同週補一次；預設強度中等。"
    )


def test_evaluate_purpose_only_includes_intensity_bias():
    out = RoleModelRenderer().to_context("trait", "n", T2_CONTENT, Purpose.evaluate, 150)

    assert "強度" in out
    assert "每週 4–5 次" not in out


def test_revise_purpose_for_trait_uses_missed_policy_and_progression_rate():
    out = RoleModelRenderer().to_context("trait", "n", T2_CONTENT, Purpose.revise, 300)

    assert "10%" in out
    assert "在同週補一次" in out
    assert "每次 30–60 分鐘" not in out


def test_persona_generate_includes_all_five_sections():
    out = RoleModelRenderer().to_context("persona", "n", P2_CONTENT, Purpose.generate, 600)

    for heading in ("原則", "每週結構", "進度指標", "常見失敗點", "里程碑範例"):
        assert f"## {heading}" in out
    assert "適用性" not in out


def test_persona_evaluate_includes_summary_and_applicability():
    out = RoleModelRenderer().to_context("persona", "n", P2_CONTENT, Purpose.evaluate, 150)

    assert "八成訓練量放在輕鬆配速" in out
    assert "## 適用性" in out
    assert "想首馬完賽者" in out
    assert "## 原則" not in out


def test_revise_purpose_uses_pitfalls_and_weekly_structure():
    out = RoleModelRenderer().to_context("persona", "n", P2_CONTENT, Purpose.revise, 300)

    assert "## 常見失敗點" in out
    assert "## 每週結構" in out
    assert "## 原則" not in out
    assert out.index("## 常見失敗點") < out.index("## 每週結構")


def test_budget_truncates_from_the_tail_by_whole_sections():
    full = RoleModelRenderer().to_context("persona", "n", P2_CONTENT, Purpose.generate, 600)
    tight = RoleModelRenderer().to_context("persona", "n", P2_CONTENT, Purpose.generate, 60)

    assert tight in full or full.startswith(tight.rstrip())
    assert "常見失敗點" not in tight
    assert estimate_tokens(tight) <= 60


def test_a_single_oversized_section_is_still_returned():
    tiny = RoleModelRenderer().to_context("persona", "n", P2_CONTENT, Purpose.generate, 1)

    assert tiny.startswith("## 原則")
    assert "## 每週結構" not in tiny


def test_empty_content_renders_empty_string():
    assert RoleModelRenderer().to_context("persona", "n", {}, Purpose.generate, 600) == ""
    assert RoleModelRenderer().to_context("trait", "n", {}, Purpose.generate, 600) == ""


def test_null_renderer_always_returns_empty_string():
    assert NullRoleModelRenderer().to_context("trait", "n", T2_CONTENT, Purpose.generate, 600) == ""
