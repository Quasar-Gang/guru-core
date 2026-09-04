"""Every revision ever asked for on one plan (PRD 3.8: `GET /plans/{id}/revisions`)."""

from uuid import UUID

from packages.repo import PlanRevisionRepo
from services.api.application.get_plan import GetPlan
from services.api.application.get_revision import RevisionView, revision_view

__all__ = ["ListRevisions"]


class ListRevisions:
    """Oldest first, exactly as the repo returns them."""

    def __init__(self, revisions: PlanRevisionRepo, get_plan: GetPlan) -> None:
        self._revisions = revisions
        self._get_plan = get_plan

    async def __call__(self, user_id: UUID, plan_id: UUID) -> list[RevisionView]:
        await self._get_plan.load(user_id, plan_id)
        rows = await self._revisions.list_for_plan(plan_id)
        return [revision_view(revision) for revision in rows]
