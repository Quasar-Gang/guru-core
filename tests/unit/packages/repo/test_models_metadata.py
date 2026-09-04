from packages.repo.models import Base

EXPECTED = {
    "users",
    "profiles",
    "oauth_connections",
    "imports",
    "documents",
    "role_models",
    "plan_sessions",
    "followup_rounds",
    "plans",
    "plan_tasks",
    "checkins",
    "plan_revisions",
    "plan_exports",
    "llm_calls",
}


def test_all_tables_declared():
    assert set(Base.metadata.tables) == EXPECTED


def test_every_model_declares_owner():
    for mapper in Base.registry.mappers:
        doc = mapper.class_.__doc__ or ""
        assert doc.strip().startswith("Owner:"), mapper.class_.__name__


def test_plan_tasks_unique_constraint():
    cols = {
        tuple(sorted(c.name for c in con.columns))  # type: ignore[attr-defined]
        for con in Base.metadata.tables["plan_tasks"].constraints
        if con.__class__.__name__ == "UniqueConstraint"
    }
    assert ("occurrence", "plan_id", "template_key", "week_index") in cols
