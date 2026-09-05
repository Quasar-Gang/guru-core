"""The catalogue's one hard rule: every Role Model states its cost."""

from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from services.catalog.domain.errors import InvalidTag
from services.catalog.domain.tags import load_tag_vocabulary
from services.catalog.domain.template import RoleModelTemplate
from services.catalog.settings import CatalogSettings

SHIPPED = ["S-1", "S-2", "S-3", "S-4", "S-5", "S-6"]


def seeds() -> list[dict[str, Any]]:
    path = CatalogSettings(_env_file=None).seeds_path
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def template(**overrides: object) -> RoleModelTemplate:
    base: dict[str, object] = {
        "code": "S-7",
        "name": "The Quiet Maintainer",
        "vision": "Keep the things other people depend on working.",
        "five_year_path": "Be the person a system outlives.",
        "must_accumulate": "Patience, and a reputation for reliability.",
        "cost": "Invisible work is invisible when promotions are decided.",
    }
    return RoleModelTemplate.model_validate(base | overrides)


class TestTheShippedSix:
    def test_there_are_six_of_them(self):
        assert [entry["code"] for entry in seeds()] == SHIPPED

    def test_every_one_validates_as_a_template(self):
        assert len([RoleModelTemplate.model_validate(entry) for entry in seeds()]) == 6

    def test_every_one_states_a_cost(self):
        """A template with no stated trade-off is a popularity contest entry."""
        assert all(entry["cost"].strip() for entry in seeds())

    def test_every_one_carries_a_valid_tag_set(self):
        vocabulary = load_tag_vocabulary()
        for entry in seeds():
            assert vocabulary.validate_tags(list(entry["tags"]))


class TestTheCostRule:
    def test_a_blank_cost_is_a_missing_cost(self):
        with pytest.raises(ValidationError):
            template(cost="")

    def test_whitespace_alone_is_not_a_cost(self):
        with pytest.raises(ValidationError):
            template(cost="   ")

    def test_a_stated_cost_passes(self):
        assert template().cost


class TestTheTagVocabulary:
    def test_a_tag_must_be_namespaced(self):
        with pytest.raises(InvalidTag, match="namespace:value"):
            load_tag_vocabulary().validate_tags(["depth"])

    def test_an_unknown_namespace_is_rejected(self):
        with pytest.raises(InvalidTag, match="unknown tag namespace"):
            load_tag_vocabulary().validate_tags(["mood:calm"])

    def test_a_closed_namespace_only_takes_its_own_values(self):
        with pytest.raises(InvalidTag, match="is closed"):
            load_tag_vocabulary().validate_tags(["area:hobbies"])

    def test_tags_are_normalized_and_deduplicated(self):
        assert load_tag_vocabulary().validate_tags(["Shape:Depth", "shape:depth"]) == [
            "shape:depth"
        ]

    def test_there_is_a_ceiling_on_how_many_tags_one_template_may_carry(self):
        vocabulary = load_tag_vocabulary()
        ceiling = vocabulary.value_rules.max_tags_per_record
        too_many = [f"shape:tag-{index}" for index in range(ceiling + 1)]
        with pytest.raises(InvalidTag, match="at most"):
            vocabulary.validate_tags(too_many)
