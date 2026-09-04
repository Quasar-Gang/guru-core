"""The shipped seeds must satisfy the tag vocabulary and the content schema (plan Task 29)."""

from pathlib import Path
from typing import Any

import yaml

from services.role_model.domain import load_tag_vocab, parse_content, validate_tags

SEEDS_DIR = Path(__file__).resolve().parents[3] / "seeds" / "role_models"


def _all_seed_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(SEEDS_DIR.glob("*.yaml")):
        rows.extend(yaml.safe_load(path.read_text(encoding="utf-8"))["role_models"])
    return rows


def _seed(name: str) -> dict[str, Any]:
    return next(row for row in _all_seed_rows() if row["name"] == name)


def test_all_seed_files_pass_validation() -> None:
    vocab = load_tag_vocab()
    for row in _all_seed_rows():
        validate_tags(row["tags"], row["kind"], vocab)
        parse_content(row["kind"], row["content"])


def test_seed_counts_match_prd() -> None:
    rows = _all_seed_rows()
    assert len([r for r in rows if r["kind"] == "trait"]) == 3
    assert len([r for r in rows if r["kind"] == "persona"]) == 9


def test_trait_pacing_values_match_prd_table() -> None:
    t1 = _seed("輕鬆寫意型")["content"]["pacing"]
    assert t1["sessions_per_week"] == [2, 3]
    assert t1["session_minutes"] == [20, 45]
    assert t1["rest_days_min"] == 2 and t1["progression_rate"] == 0.05
    assert t1["missed_policy"] == "none" and t1["deload_every_weeks"] is None
    assert t1["intensity_bias"] == "low"

    t2 = _seed("穩扎穩打型")["content"]["pacing"]
    assert t2["sessions_per_week"] == [4, 5]
    assert t2["session_minutes"] == [30, 60]
    assert t2["rest_days_min"] == 1 and t2["progression_rate"] == 0.10
    assert t2["missed_policy"] == "same-week" and t2["deload_every_weeks"] is None
    assert t2["intensity_bias"] == "medium"

    t3 = _seed("地獄模式型")["content"]["pacing"]
    assert t3["sessions_per_week"] == [6, 6]
    assert t3["session_minutes"] == [60, 90]
    assert t3["rest_days_min"] == 1 and t3["progression_rate"] == 0.15
    assert t3["missed_policy"] == "next-day" and t3["deload_every_weeks"] == 3
    assert t3["intensity_bias"] == "high"


def test_persona_names_and_tags_match_prd() -> None:
    personas = {row["name"]: row for row in _all_seed_rows() if row["kind"] == "persona"}
    assert set(personas) == {
        "Stephen Curry 型",
        "Eliud Kipchoge 型",
        "上班族減脂型",
        "Steve Kaufmann 型",
        "Scott Young 型",
        "在職考證照型",
        "Warren Buffett 型",
        "John Bogle 型",
        "存第一桶金型",
    }
    for row in personas.values():
        assert any(tag.startswith("domain:") for tag in row["tags"])
        assert row["content"]["sections"]["applicability"]["good_for"]
