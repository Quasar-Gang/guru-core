"""The four Fit Verdict invariants, which are what makes a verdict arguable."""

from services.engine.domain.verdict import (
    Citation,
    Evidence,
    FitVerdictDraft,
    FitVerdictSet,
    Probe,
    verdict_violations,
)

DIMENSIONS = ["work", "learning", "unclassified", "social", "capacity"]
CODES = ["S-1", "S-2"]


def item(stance: str, dimension: str = "work") -> Evidence:
    return Evidence(
        stance=stance,  # type: ignore[arg-type]
        text="Something the reports actually say.",
        cites=Citation(dimension=dimension, fact="a fact from that column"),  # type: ignore[arg-type]
    )


def draft(code: str = "S-1", evidence: list[Evidence] | None = None) -> FitVerdictDraft:
    return FitVerdictDraft(
        role_model_code=code,
        fit="strongly_consistent",
        verdict="One line stating the finding.",
        note="What it means, and what it does not mean.",
        evidence=evidence
        if evidence is not None
        else [item("for"), item("against"), item("for"), item("against"), item("for")],
        probe=Probe(statement="The one cheap test.", cost="Three evenings; failing costs nothing."),
    )


def check(*drafts: FitVerdictDraft, codes: list[str] | None = None) -> list[str]:
    return verdict_violations(
        FitVerdictSet(verdicts=list(drafts)),
        expected_codes=codes if codes is not None else [d.role_model_code for d in drafts],
        available_dimensions=DIMENSIONS,
    )


def test_a_well_formed_set_passes():
    assert check(draft("S-1"), draft("S-2")) == []


def test_every_shape_must_be_scored():
    """The Recommender does not narrow to one; it scores all of them and chooses nothing."""
    violations = check(draft("S-1"), codes=CODES)
    assert any("'S-2' is required" in message for message in violations)


def test_a_shape_outside_the_catalogue_is_rejected():
    violations = check(draft("S-9"), codes=CODES)
    assert any("not in the catalogue" in message for message in violations)


def test_a_shape_may_not_be_scored_twice():
    violations = check(draft("S-1"), draft("S-1"))
    assert any("at most once" in message for message in violations)


def test_there_must_be_exactly_five_evidence_items():
    violations = check(draft("S-1", [item("for"), item("against")]))
    assert any("exactly 5" in message for message in violations)


def test_a_verdict_that_only_agrees_is_a_compliment_not_a_diagnosis():
    violations = check(draft("S-1", [item("for") for _ in range(5)]))
    assert any("at least one 'against'" in message for message in violations)


def test_a_verdict_that_only_disagrees_is_rejected_the_same_way():
    violations = check(draft("S-1", [item("against") for _ in range(5)]))
    assert any("at least one 'for'" in message for message in violations)


def test_every_item_must_cite_a_report_this_run_produced():
    """An uncited claim is not evidence, and an uncited verdict cannot be argued with."""
    evidence = [item("for"), item("against"), item("for"), item("against"), item("for", "money")]
    violations = check(draft("S-1", evidence))
    assert any("'money'" in message and "no report" in message for message in violations)


def test_a_violation_names_the_verdict_it_belongs_to():
    violations = check(draft("S-2", [item("for")]))
    assert all("'S-2'" in message for message in violations)
