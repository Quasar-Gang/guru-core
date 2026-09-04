import json
from pathlib import Path
from typing import Any

import pytest

from packages.llm import PromptRegistry
from services.plan_engine.domain import PlanTemplateOutput, ReadinessOutput

ROOT = Path(__file__).resolve().parents[4]
PROMPTS = ROOT / "packages" / "llm" / "prompts"
FIXTURES = ROOT / "tests" / "fixtures" / "llm"

PROMPT_NAMES = [
    "evaluate_readiness",
    "generate_plans",
    "revise_plan",
    "recommend_role_model",
    "smoke",
]


def _full_context() -> dict[str, Any]:
    return {
        "goal": "12 週 5K 跑進 30 分",
        "intake": {"age_band": "30-39", "job": "軟體工程師"},
        "timezone": "Asia/Taipei",
        "documents_summary": ["2026 上半年跑步紀錄：平均 5K 38 分"],
        "existing_schedule": ["週三 19:00-21:00 例會"],
        "trait_context": "穩扎穩打型：每週 4–5 次、單次 30–60 分。",
        "persona_context": "Eliud Kipchoge 型：80/20 低強度為主。",
        "previous_rounds": [
            {
                "round_no": 0,
                "questions": [{"metric_id": "capacity", "text": "每週能練幾次？"}],
                "answers": [{"metric_id": "capacity", "answer": "平日 2 晚 + 週六早上"}],
            }
        ],
        "metrics_yaml": "required:\n  - id: goal_outcome\n",
        "max_questions": 5,
        "options_per_question": 3,
        "default_duration_weeks": 12,
        "pacing_context": "每週最多 5 次，單次不超過 60 分，每週至少 1 天完全休息。",
        "current_template": {"title": "12 週 5K 跑進 30 分", "duration_weeks": 12},
        "strategy": "postpone",
        "note": "出差兩週",
        "progress_summary": "前 4 週完成率 62%，長跑常缺席。",
        "remaining_weeks": 8,
        "profile_summary": "上班族，想穩定累積，目標跑步。",
        "candidates": [
            {
                "id": "9f1c1f0c-4f7a-4a1e-9b3f-6a1f2a3b4c5d",
                "name": "Eliud Kipchoge 型",
                "summary": "80/20 低強度為主",
                "tags": ["domain:fitness"],
            }
        ],
        "max_recommendations": 3,
    }


@pytest.mark.parametrize("name", PROMPT_NAMES)
def test_all_prompts_render_without_error(name: str):
    r = PromptRegistry(PROMPTS).render(name, _full_context())
    assert r.system and r.user and r.version


@pytest.mark.parametrize("name", ["evaluate_readiness", "generate_plans", "revise_plan"])
def test_prompts_render_with_violation_feedback(name: str):
    ctx = _full_context()
    ctx["_violations"] = ["questions must not be empty"]
    ctx["_previous_output"] = {"ready": False, "questions": []}
    r = PromptRegistry(PROMPTS).render(name, ctx)
    assert "questions must not be empty" in r.user


def test_constraints_appear_at_end_of_user_prompt():
    r = PromptRegistry(PROMPTS).render("generate_plans", _full_context())
    tail = r.user[-800:]
    assert "duration_weeks" in tail and "difficulty" in tail


def test_evaluate_readiness_constraints_appear_at_end():
    r = PromptRegistry(PROMPTS).render("evaluate_readiness", _full_context())
    tail = r.user[-800:]
    assert "JSON" in tail and "allow_skip" in tail and "metric_id" in tail


def test_fixtures_validate_against_output_schemas():
    ReadinessOutput.model_validate_json((FIXTURES / "evaluate_readiness.json").read_text())
    PlanTemplateOutput.model_validate_json((FIXTURES / "generate_plans.json").read_text())


def test_revise_plan_fixture_has_template_and_rationale():
    payload = json.loads((FIXTURES / "revise_plan.json").read_text())
    assert payload["rationale"]
    PlanTemplateOutput.model_validate({"template": payload["template"]})


def test_recommend_role_model_fixture_shape():
    payload = json.loads((FIXTURES / "recommend_role_model.json").read_text())
    assert 1 <= len(payload["recommendations"]) <= 3
    for item in payload["recommendations"]:
        assert item["role_model_id"] and item["name"] and item["reason"]
