"""Read one plan revision, diff and all (PRD 3.8: `GET /plans/{id}/revisions/{rev_id}`).

The view models here are also what `list_revisions` and `decide_revision` return.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from packages.repo import PlanRevisionRepo
from packages.repo.entities import PlanRevision
from services.api.application.get_plan import GetPlan
from services.api.domain.errors import NotFound

__all__ = [
    "GetRevision",
    "RevisionDiffSummary",
    "RevisionView",
    "TaskDiffEntry",
    "TaskSnapshot",
    "revision_view",
]

#: Deliberate duplicate of `services/plan_engine/domain/diff.py`. Services must not import
#: each other, so the Plan Engine writes these entries into `plan_revisions.diff` as JSON
#: and the API reads that JSON back through the models below — the same arrangement as the
#: duplicated `Pacing` and `FollowupQuestion`. Change one side, change the other.
DiffKind = Literal[
    "added",
    "moved",
    "removed",
    "shortened",
    "lengthened",
    "reduced",
    "unchanged",
]

#: The kinds `RevisionDiffSummary` counts, in field order.
_SUMMARY_KINDS = ("added", "moved", "removed", "shortened", "lengthened", "unchanged")


class TaskSnapshot(BaseModel):
    """One side of a diff entry: how a task looks before or after the revision."""

    title: str
    start_at: datetime
    end_at: datetime
    all_day: bool


class TaskDiffEntry(BaseModel):
    """One entry of `plan_revisions.diff`, aligned on the scheduler's stable task key."""

    template_key: str
    week_index: int
    occurrence: int
    kind: DiffKind
    title: str
    before: TaskSnapshot | None
    after: TaskSnapshot | None


class RevisionDiffSummary(BaseModel):
    """How many entries of each kind the diff holds; the app renders this as a headline."""

    added: int = 0
    moved: int = 0
    removed: int = 0
    shortened: int = 0
    lengthened: int = 0
    unchanged: int = 0


class RevisionView(BaseModel):
    id: UUID
    plan_id: UUID
    strategy: str
    status: str
    rationale: str | None
    diff: list[TaskDiffEntry]
    summary: RevisionDiffSummary
    created_at: datetime
    decided_at: datetime | None


def revision_view(revision: PlanRevision) -> RevisionView:
    """Render one `plan_revisions` row; a revision without a proposal has an empty diff."""
    entries = [TaskDiffEntry.model_validate(entry) for entry in revision.diff or []]
    counts = {kind: 0 for kind in _SUMMARY_KINDS}
    for entry in entries:
        if entry.kind in counts:
            counts[entry.kind] += 1
    return RevisionView(
        id=revision.id,
        plan_id=revision.plan_id,
        strategy=revision.strategy,
        status=revision.status,
        # Until the engine proposes something, `rationale` still holds the user's own note.
        rationale=revision.rationale,
        diff=entries,
        summary=RevisionDiffSummary(**counts),
        created_at=revision.created_at,
        decided_at=revision.decided_at,
    )


class GetRevision:
    """Also the single place the other revision use cases load a revision from."""

    def __init__(self, revisions: PlanRevisionRepo, get_plan: GetPlan) -> None:
        self._revisions = revisions
        self._get_plan = get_plan

    async def __call__(self, user_id: UUID, plan_id: UUID, revision_id: UUID) -> RevisionView:
        return revision_view(await self.load(user_id, plan_id, revision_id))

    async def load(self, user_id: UUID, plan_id: UUID, revision_id: UUID) -> PlanRevision:
        """Fetch a revision of a plan owned by `user_id`, or raise `NotFound`."""
        await self._get_plan.load(user_id, plan_id)
        revision = await self._revisions.get(plan_id, revision_id)
        if revision is None:
            raise NotFound(f"plan revision not found: {revision_id}")
        return revision
