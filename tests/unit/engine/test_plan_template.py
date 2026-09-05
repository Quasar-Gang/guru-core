"""The two shape rules — milestones nest, tasks do not — are enforced, not documented."""

import pytest
from pydantic import ValidationError

from services.engine.domain.plan_template import MilestoneNode, PlanTemplate, TaskSpec, flatten


def node(key: str, *children: MilestoneNode, target_week: int = 3) -> MilestoneNode:
    return MilestoneNode(
        key=key,
        title=key.replace("_", " ").title(),
        metric="Done or not",
        target_week=target_week,
        children=list(children),
    )


def task(key: str = "work", milestone_key: str = "probe", **overrides: object) -> TaskSpec:
    base: dict[str, object] = {
        "key": key,
        "milestone_key": milestone_key,
        "title": "Work",
        "task_type": "session",
        "area": "career",
        "day_hint": "any",
        "slot_hint": "any",
        "duration_minutes": 45,
        "times_per_week": 2,
        "week_start": 0,
        "week_end": 3,
    }
    return TaskSpec.model_validate(base | overrides)


def build(**overrides: object) -> PlanTemplate:
    base: dict[str, object] = {
        "title": "A quarter",
        "duration_weeks": 4,
        "success_criteria": ["Finished."],
        "milestones": [node("probe")],
        "tasks": [task()],
    }
    return PlanTemplate.model_validate(base | overrides)


def test_a_valid_template_round_trips():
    template = build()
    assert template.duration_weeks == 4
    assert flatten(template.milestones)[0].key == "probe"


def test_milestones_nest_and_flatten_with_their_place_in_the_tree():
    template = build(
        milestones=[node("probe", node("draft", node("outline", target_week=1), target_week=2))]
    )
    flat = flatten(template.milestones)
    assert [(item.key, item.depth, item.parent_key) for item in flat] == [
        ("probe", 0, None),
        ("draft", 1, "probe"),
        ("outline", 2, "draft"),
    ]


def test_the_tree_may_not_nest_forever():
    deep = node("a", node("b", node("c", node("d", target_week=0), target_week=1), target_week=2))
    with pytest.raises(ValidationError, match="deep"):
        build(milestones=[deep])


def test_milestone_keys_must_be_unique_across_the_whole_tree():
    with pytest.raises(ValidationError, match="unique"):
        build(milestones=[node("probe", node("probe", target_week=1))])


def test_a_task_must_name_a_milestone_that_exists():
    """There is no `parent_id` on a task and no task without a milestone: flat by construction."""
    with pytest.raises(ValidationError, match="unknown milestone"):
        build(tasks=[task(milestone_key="nowhere")])


def test_a_task_may_not_run_past_the_plan():
    with pytest.raises(ValidationError, match="beyond the plan"):
        build(tasks=[task(week_end=9)])


def test_a_milestone_may_not_target_a_week_the_plan_never_reaches():
    with pytest.raises(ValidationError, match="beyond the plan"):
        build(milestones=[node("probe", target_week=9)])


def test_a_task_range_must_run_forwards():
    with pytest.raises(ValidationError, match="after week_end"):
        build(tasks=[task(week_start=3, week_end=1)])


def test_task_keys_must_be_unique():
    with pytest.raises(ValidationError, match="task keys"):
        build(tasks=[task("work"), task("work", slot_hint="morning")])
