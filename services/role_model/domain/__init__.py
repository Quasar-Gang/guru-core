"""Role model domain: tag vocabulary and content schemas (PRD 12.3 / 12.4)."""

from services.role_model.domain.content import (
    Applicability,
    Pacing,
    PersonaContent,
    PersonaSections,
    Provenance,
    RoleModelContent,
    Source,
    TraitContent,
    parse_content,
)
from services.role_model.domain.errors import InvalidContent, InvalidTag
from services.role_model.domain.renderer import (
    NullRoleModelRenderer,
    RoleModelRenderer,
    estimate_tokens,
)
from services.role_model.domain.scoring import (
    RoleModelRow,
    ScoredCandidate,
    UserSignals,
    score_candidates,
)
from services.role_model.domain.tags import (
    TagVocab,
    ValueRules,
    learn_values,
    load_tag_vocab,
    parse_tag,
    validate_tags,
)

__all__ = [
    "Applicability",
    "InvalidContent",
    "InvalidTag",
    "NullRoleModelRenderer",
    "Pacing",
    "PersonaContent",
    "PersonaSections",
    "Provenance",
    "RoleModelContent",
    "RoleModelRenderer",
    "RoleModelRow",
    "ScoredCandidate",
    "Source",
    "TagVocab",
    "TraitContent",
    "UserSignals",
    "ValueRules",
    "estimate_tokens",
    "learn_values",
    "load_tag_vocab",
    "parse_content",
    "parse_tag",
    "score_candidates",
    "validate_tags",
]
