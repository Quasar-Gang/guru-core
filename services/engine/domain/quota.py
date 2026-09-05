"""The Quota: the standing allowance Q-3 declares, and the order things get cut in.

> "If you could only keep two this quarter, which would you let go of first?"

Everyone claims career, relationships and health matter equally, so the question forces a
ranking. The answer becomes a ceiling the Schedule may not exceed and a cut order for when
capacity runs short — which is the only way a plan can shrink without the user having to
decide, item by item, what to abandon.

Capacity says what is physically possible; the Quota says what has been allowed. The
Schedule must satisfy both, and when they conflict the cut order decides.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from packages.config import CONFIG_DIR, load_yaml_config
from services.engine.domain.plan_template import Area

__all__ = ["AREAS", "Quota", "QuotaConfig", "load_quota_config"]

#: In the order Q-3 puts them to the user.
AREAS: tuple[Area, ...] = ("career", "relationships", "health")


class Quota(BaseModel):
    """What the Schedule may spend in one week, and what it drops first when it cannot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    drop_first: Area
    weekly_minutes: int = Field(ge=0)

    @property
    def cut_order(self) -> tuple[Area, ...]:
        """The area named by Q-3 first, then the rest in the order the question lists them."""
        return (self.drop_first, *(area for area in AREAS if area != self.drop_first))


class QuotaConfig(BaseModel):
    """`config/quota.yaml`: what to assume until Q-3 has been answered."""

    model_config = ConfigDict(extra="forbid")

    default_drop_first: Area = "career"
    default_weekly_minutes: int = Field(default=300, ge=0)

    def fallback(self) -> Quota:
        """A quota for a user who skipped Q-3 — deliberately modest, and always stated."""
        return Quota(drop_first=self.default_drop_first, weekly_minutes=self.default_weekly_minutes)


def load_quota_config(path: Path | None = None) -> QuotaConfig:
    return load_yaml_config(path or CONFIG_DIR / "quota.yaml", QuotaConfig)
