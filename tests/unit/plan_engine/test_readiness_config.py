from services.plan_engine.domain import (
    FollowupQuestion,
    ReadinessOutput,
    load_readiness_config,
    readiness_rules,
)

cfg = load_readiness_config()


def _q(qid: str, metric_id: str, options: list[str] | None = None) -> FollowupQuestion:
    return FollowupQuestion(
        id=qid,
        metric_id=metric_id,
        text=f"關於 {metric_id} 想確認一下？",
        options=options or ["選項一", "選項二", "選項三"],
    )


def _violations(out: ReadinessOutput, asked: set[str] | None = None) -> list[str]:
    rules = readiness_rules(cfg, asked_metric_ids=asked or set())
    return [v for r in rules for v in r(out)]


def test_readiness_config_loads_all_four_required():
    assert cfg.required_ids() == ["goal_outcome", "horizon", "capacity", "baseline"]
    assert cfg.max_followup_rounds == 2
    assert cfg.max_questions_per_round == 5
    assert cfg.options_per_question == 3


def test_readiness_config_exposes_domain_probe_and_helpful():
    assert cfg.domain_probe.id == "domain_specific"
    assert cfg.domain_probe.max_items == 2
    assert "difficulty_preference" in {m.id for m in cfg.helpful}
    assert cfg.ask_order == ["required", "domain_probe", "helpful"]


def test_readiness_rule_rejects_empty_questions_when_not_ready():
    out = ReadinessOutput(ready=False, missing=["capacity"], questions=[])
    assert any("questions" in v for v in _violations(out))


def test_readiness_rule_rejects_missing_when_ready():
    out = ReadinessOutput(ready=True, missing=["capacity"], questions=[])
    assert any("missing" in v for v in _violations(out))


def test_readiness_rule_rejects_unknown_metric_id():
    out = ReadinessOutput(ready=False, missing=[], questions=[_q("q1", "nope")])
    assert any("nope" in v for v in _violations(out))


def test_readiness_rule_rejects_duplicate_metric_in_round():
    out = ReadinessOutput(
        ready=False,
        missing=["capacity"],
        questions=[_q("q1", "capacity"), _q("q2", "capacity")],
    )
    assert any("capacity" in v for v in _violations(out))


def test_readiness_rule_rejects_repeat_of_previous_round():
    out = ReadinessOutput(ready=False, missing=["capacity"], questions=[_q("q1", "capacity")])
    assert any("capacity" in v for v in _violations(out, asked={"capacity"}))


def test_readiness_rule_rejects_non_distinct_options():
    out = ReadinessOutput(
        ready=False,
        missing=["capacity"],
        questions=[_q("q1", "capacity", ["一樣", "一樣", "不一樣"])],
    )
    assert any("options" in v for v in _violations(out))


def test_readiness_rule_rejects_blank_option():
    out = ReadinessOutput(
        ready=False,
        missing=["capacity"],
        questions=[_q("q1", "capacity", ["一", "  ", "三"])],
    )
    assert any("options" in v for v in _violations(out))


def test_readiness_rule_accepts_domain_probe_and_helpful_metric_ids():
    out = ReadinessOutput(
        ready=False,
        missing=["capacity"],
        questions=[_q("q1", "domain_specific"), _q("q2", "difficulty_preference")],
    )
    assert _violations(out) == []


def test_readiness_rule_passes_valid_output():
    out = ReadinessOutput(ready=False, missing=["capacity"], questions=[_q("q1", "capacity")])
    assert _violations(out) == []
    assert _violations(ReadinessOutput(ready=True)) == []
