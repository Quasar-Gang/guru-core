"""Report dimensions — the columns the Analyzer lays the data out in.

Loaded from `config/report_dimensions.yaml` so the set is data, not a hard-coded list.
`unclassified` is a dimension like any other, deliberately: unnamed time is where the
difference between the life someone describes and the life they run tends to hide, so it
is kept visible rather than tidied away.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.config import CONFIG_DIR, load_yaml_config

__all__ = [
    "DIMENSIONS",
    "Dimension",
    "DimensionSpec",
    "ReportDimensionsConfig",
    "load_dimensions_config",
]

Dimension = Literal["work", "social", "learning", "exercise", "capacity", "money", "unclassified"]

#: The literal's members, in the order they are shown.
DIMENSIONS: tuple[Dimension, ...] = (
    "work",
    "social",
    "learning",
    "exercise",
    "capacity",
    "money",
    "unclassified",
)


class DimensionSpec(BaseModel):
    """What one column means, and whether a Report for it is always expected."""

    model_config = ConfigDict(extra="forbid")

    key: Dimension
    label: str
    description: str
    #: A dimension whose source is optional — `money` needs a card statement — is only
    #: required once that source has been uploaded.
    requires_source: str | None = None


class ReportDimensionsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: How far back a Report looks. The prototype reads 26 weeks; a fixed window keeps two
    #: runs comparable, which is what Station 3 needs.
    window_weeks: int = Field(default=26, ge=1, le=520)
    dimensions: list[DimensionSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def covers_every_dimension(self) -> ReportDimensionsConfig:
        configured = [spec.key for spec in self.dimensions]
        missing = [name for name in DIMENSIONS if name not in configured]
        if missing:
            raise ValueError(f"report_dimensions.yaml is missing: {', '.join(missing)}")
        return self

    def required(self, available_sources: frozenset[str]) -> list[Dimension]:
        """The dimensions a Report must exist for, given what the user actually uploaded."""
        return [
            spec.key
            for spec in self.dimensions
            if spec.requires_source is None or spec.requires_source in available_sources
        ]

    def spec(self, dimension: Dimension) -> DimensionSpec:
        return next(spec for spec in self.dimensions if spec.key == dimension)


def load_dimensions_config(path: Path | None = None) -> ReportDimensionsConfig:
    return load_yaml_config(path or CONFIG_DIR / "report_dimensions.yaml", ReportDimensionsConfig)
