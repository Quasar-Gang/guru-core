"""Role model content schemas (PRD 12.4 / 14.2)."""

from datetime import date

import pytest

from services.role_model.domain import (
    InvalidContent,
    PersonaContent,
    TraitContent,
    parse_content,
)

# PRD 14.2 — T2 steady-progress trait
PRD_T2_EXAMPLE = {
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
PRD_P2_EXAMPLE = {
    "summary": "Eighty percent easy running, with periodization and one weekly long run.",
    "sections": {
        "principles": [
            "Run 80% of your volume at a conversational easy pace.",
            "Schedule only one or two hard sessions a week; everything else is easy.",
            "Progress volume week by week, adding no more than 10% over the previous week.",
            "Treat recovery and sleep as part of training, not as an afterthought.",
        ],
        "weekly_structure": (
            "Five sessions a week: three easy runs (30-50 min), one hard session "
            "(intervals or tempo), and one long slow run on the weekend that gets "
            "longer each week. The other two days are full rest or light stretching."
        ),
        "progress_metrics": [
            "Heart rate at the same pace drops week over week",
            "Long-run duration increases week over week",
            "A timed run over a fixed distance every four weeks, compared against the last one",
        ],
        "pitfalls": [
            "Running easy days too fast, so no day is a real recovery day",
            "Ramping weekly mileage too quickly and triggering shin or knee pain",
            "Only running long, skipping hard sessions, and stalling out on pace",
        ],
        "applicability": {
            "good_for": [
                "first-time marathoners",
                "runners chasing a 5K/10K personal best",
                "runners who can train four or more times a week",
            ],
            "not_for": [
                "runners with an unhealed lower-body injury",
                "people who can only train twice a week",
                "people whose main goal is building muscle",
            ],
        },
        "example_milestones": [
            "Week 4: run 45 minutes continuously without stopping",
            "Week 8: complete a 12 km long run",
            "Week 12: improve the 5 km time trial by at least 8% over the baseline",
        ],
    },
    "provenance": {
        "sources": [
            {
                "title": "Endurance training principles drawn from public reporting and interviews",
                "url": "https://example.com/placeholder",
                "accessed_at": "2026-09-05",
            }
        ],
        "confidence": "medium",
        "author": "guru team",
        "notes": "publicly verifiable training principles only; no biography or private details",
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
    c = parse_content("persona", PRD_P2_EXAMPLE)  # the Kipchoge example from PRD 14.2
    assert isinstance(c, PersonaContent)
    assert c.sections.principles and c.sections.applicability.good_for
    assert len(c.sections.pitfalls) == 3
    assert c.provenance.sources[0].accessed_at == date(2026, 9, 5)
