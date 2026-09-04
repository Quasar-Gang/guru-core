"""Tag vocabulary loading and validation (PRD 12.3)."""

import pytest

from services.role_model.domain import (
    InvalidTag,
    learn_values,
    load_tag_vocab,
    parse_tag,
    validate_tags,
)

VOCAB = load_tag_vocab()


def test_loads_real_vocab_file():
    assert VOCAB.version == 1
    assert VOCAB.mode == "lenient"
    assert "domain" in VOCAB.namespaces
    assert VOCAB.value_rules.max_tags_per_record == 12
    assert VOCAB.required_tags["persona"] == ["domain", "goal"]


def test_parse_tag_splits_namespace_and_value():
    assert parse_tag("domain:fitness") == ("domain", "fitness")


def test_parse_tag_rejects_missing_colon():
    with pytest.raises(InvalidTag):
        parse_tag("fitness")


def test_rejects_unknown_namespace():
    with pytest.raises(InvalidTag, match="foo"):
        validate("foo:bar")


def test_rejects_bad_value_pattern():
    with pytest.raises(InvalidTag):
        validate("domain:Fitness")  # 大寫不合法


def test_rejects_too_long_value():
    with pytest.raises(InvalidTag):
        validate("domain:" + "a" * 33, "goal:skill")


def test_enum_only_namespace_rejects_unknown_value():
    with pytest.raises(InvalidTag, match="level"):
        validate("domain:x", "goal:y", "level:godlike")


def test_enum_only_namespace_accepts_known_value():
    validate("domain:x", "goal:y", "level:beginner")


def test_persona_requires_domain_and_goal():
    with pytest.raises(InvalidTag, match="goal"):
        validate("domain:fitness")


def test_trait_has_no_required_tags():
    validate_tags(["cadence:daily"], "trait", VOCAB)  # 不 raise


def test_unknown_kind_has_no_required_tags():
    validate_tags(["cadence:daily"], "whatever", VOCAB)


def test_lenient_mode_accepts_new_domain_value():
    validate("domain:woodworking", "goal:skill")


def test_strict_mode_rejects_new_value():
    strict = VOCAB.model_copy(update={"mode": "strict"})
    with pytest.raises(InvalidTag):
        validate_tags(["domain:woodworking", "goal:skill"], "persona", strict)


def test_strict_mode_accepts_known_value():
    strict = VOCAB.model_copy(update={"mode": "strict"})
    validate_tags(["domain:fitness", "goal:skill"], "persona", strict)


def test_max_tags_enforced():
    tags = ["domain:fitness", "goal:skill", *[f"method:m-{i}" for i in range(11)]]
    assert len(tags) == 13
    with pytest.raises(InvalidTag):
        validate_tags(tags, "persona", VOCAB)


def test_max_tags_boundary_is_accepted():
    tags = ["domain:fitness", "goal:skill", *[f"method:m-{i}" for i in range(10)]]
    assert len(tags) == 12
    validate_tags(tags, "persona", VOCAB)


def test_learn_values_appends_without_mutating():
    before = list(VOCAB.known_values["domain"])
    learned = learn_values(["domain:woodworking", "goal:skill"], VOCAB)
    assert learned is not VOCAB
    assert VOCAB.known_values["domain"] == before
    assert "woodworking" in learned.known_values["domain"]
    assert "skill" in learned.known_values["goal"]


def test_learn_values_is_idempotent_and_skips_enum_only():
    learned = learn_values(["domain:fitness", "level:beginner"], VOCAB)
    assert learned.known_values["domain"].count("fitness") == 1
    assert "level" not in learned.known_values


def test_learn_values_creates_missing_namespace_bucket():
    learned = learn_values(["persona:running"], VOCAB)
    assert learned.known_values["persona"] == ["running"]


def validate(*tags: str) -> None:
    validate_tags(list(tags), "persona", VOCAB)
