"""What a Role Model has to state before it may enter the catalogue.

One rule carries the whole module: **every Role Model states its cost.** A template with no
stated trade-off is a popularity contest entry, won by whichever sounds best out loud. That
holds for the six shipped shapes and for anything a user writes themselves — a user-authored
template is a Role Model like any other, and must also carry a cost.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["Author", "RoleModelTemplate"]

Author = Literal["system", "user"]


class RoleModelTemplate(BaseModel):
    """The six fields that make a life shape borrowable, and nothing per-user.

    Anything computed for one person — how well it fits, what the evidence says, which probe
    to run — belongs to the Fit Verdict. Keeping that line clean is what lets the catalogue
    be shared, cached and compared.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9._-]+$")
    name: str = Field(min_length=1, max_length=128)
    vision: str = Field(min_length=1)
    five_year_path: str = Field(min_length=1)
    must_accumulate: str = Field(min_length=1)
    #: Required, and not merely non-null: a blank cost is a missing cost.
    cost: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
