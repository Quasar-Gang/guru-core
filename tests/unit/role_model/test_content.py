"""Role model content schemas (PRD 12.4 / 14.2)."""

from datetime import date

import pytest

from services.role_model.domain import (
    InvalidContent,
    PersonaContent,
    TraitContent,
    parse_content,
)

# PRD 14.2 — T2 穩扎穩打型
PRD_T2_EXAMPLE = {
    "summary": "固定節奏、線性漸進，寧可慢一點也要每週都動。",
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
        "notes": "團隊定義的執行風格，非特定人物",
    },
}

# PRD 14.2 — P2 Eliud Kipchoge 型
PRD_P2_EXAMPLE = {
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
        "sources": [
            {
                "title": "公開報導與訪談整理的耐力訓練原則",
                "url": "https://example.com/placeholder",
                "accessed_at": "2026-09-05",
            }
        ],
        "confidence": "medium",
        "author": "guru team",
        "notes": "取公開可查證的訓練原則，不含個人生平與未公開細節",
    },
}


def test_trait_content_requires_pacing():
    with pytest.raises(InvalidContent):
        parse_content("trait", {"summary": "x"})


def test_persona_content_rejects_pacing_field():
    with pytest.raises(InvalidContent):
        parse_content("persona", {"summary": "x", "pacing": PRD_T2_EXAMPLE["pacing"]})


def test_trait_content_rejects_sections_field():
    with pytest.raises(InvalidContent):
        parse_content("trait", {**PRD_T2_EXAMPLE, "sections": {}})


def test_unknown_kind_is_rejected():
    with pytest.raises(InvalidContent):
        parse_content("nonsense", {"summary": "x"})


def test_summary_length_is_capped():
    with pytest.raises(InvalidContent):
        parse_content("persona", {"summary": "x" * 121})


def test_parse_content_ignores_kind_inside_raw():
    c = parse_content("persona", {"kind": "trait", "summary": "x"})
    assert isinstance(c, PersonaContent)


def test_parse_content_does_not_mutate_input():
    raw = {"summary": "x"}
    parse_content("persona", raw)
    assert raw == {"summary": "x"}


def test_persona_only_needs_summary():
    c = parse_content("persona", {"summary": "x"})
    assert isinstance(c, PersonaContent)
    assert c.sections.principles == []
    assert c.provenance.confidence == "medium"


def test_parse_content_accepts_prd_trait_example():
    c = parse_content("trait", PRD_T2_EXAMPLE)
    assert isinstance(c, TraitContent)
    assert c.pacing.sessions_per_week == (4, 5)
    assert c.pacing.session_minutes == (30, 60)
    assert c.pacing.missed_policy == "same-week"
    assert c.pacing.deload_every_weeks is None
    assert c.pacing.intensity_bias == "medium"
    assert c.provenance.author == "guru team"


def test_parse_content_accepts_prd_example():
    c = parse_content("persona", PRD_P2_EXAMPLE)  # PRD 14.2 的 Kipchoge 範例
    assert isinstance(c, PersonaContent)
    assert c.sections.principles and c.sections.applicability.good_for
    assert len(c.sections.pitfalls) == 3
    assert c.provenance.sources[0].accessed_at == date(2026, 9, 5)
