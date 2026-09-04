"""Role model ``content`` schemas (PRD 12.4).

``kind`` discriminates the payload: ``trait`` carries numeric ``pacing``
constraints, ``persona`` carries structured prose ``sections``. Both models
forbid extra fields so a mismatched payload is rejected at the boundary.
"""

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from services.role_model.domain.errors import InvalidContent


class Pacing(BaseModel):
    """Numeric pacing constraints for a ``trait`` role model.

    Deliberate duplicate: Plan Engine defines a same-named, same-shaped model in
    ``services/plan_engine/domain/difficulty.py``. Services must not import each
    other, so the two copies are kept in sync by contract, not by code — the
    contract being the JSON stored in ``role_models.content["pacing"]`` and
    carried through ``plan_sessions.context_snapshot``. Plan Engine reads it back
    with ``Pacing.model_validate(dict)``. Change one, change the other.
    """

    model_config = ConfigDict(extra="forbid")

    sessions_per_week: tuple[int, int]
    session_minutes: tuple[int, int]
    rest_days_min: int
    progression_rate: float
    missed_policy: Literal["none", "same-week", "next-day"]
    deload_every_weeks: int | None = None
    intensity_bias: Literal["low", "medium", "high"]


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    url: str
    accessed_at: date | None = None


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[Source] = []
    confidence: Literal["high", "medium", "low"] = "medium"
    author: str | None = None
    notes: str | None = None


class Applicability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    good_for: list[str] = []
    not_for: list[str] = []


class PersonaSections(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principles: list[str] = []
    weekly_structure: str = ""
    progress_metrics: list[str] = []
    pitfalls: list[str] = []
    applicability: Applicability = Applicability()
    example_milestones: list[str] = []


class TraitContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["trait"] = "trait"
    summary: str = Field(max_length=120)
    pacing: Pacing
    provenance: Provenance = Provenance()


class PersonaContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["persona"] = "persona"
    summary: str = Field(max_length=120)
    sections: PersonaSections = PersonaSections()
    provenance: Provenance = Provenance()


RoleModelContent = Annotated[TraitContent | PersonaContent, Field(discriminator="kind")]

_CONTENT_ADAPTER: TypeAdapter[TraitContent | PersonaContent] = TypeAdapter(RoleModelContent)


def parse_content(kind: str, raw: dict[str, Any]) -> TraitContent | PersonaContent:
    """Validate ``raw`` as the content of a role model of the given ``kind``."""
    payload = {**raw, "kind": kind}
    try:
        return _CONTENT_ADAPTER.validate_python(payload)
    except ValidationError as exc:
        raise InvalidContent(f"invalid {kind} content: {exc}") from exc
