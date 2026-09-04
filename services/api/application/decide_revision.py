"""Accept or reject a proposed revision (PRD 3.8: `POST .../accept` / `.../reject`).

Accepting is the only place a revision ever touches the plan: the tasks from today on are
replaced by the proposal, and the plan's own columns follow the proposed template. Rejecting
writes nothing but the status.
"""

from datetime import UTC, date, datetime, time
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from packages.queue import QueuePort
from packages.repo import PlanExportRepo, PlanRepo, PlanRevisionRepo, PlanTaskRepo, ProfileRepo
from packages.repo.entities import NewPlanTask
from services.api.application.get_revision import GetRevision, RevisionView, revision_view
from services.api.application.list_plan_tasks import resolve_timezone
from services.api.application.ports import ClockPort
from services.api.application.update_plan_task import enqueue_incremental_export
from services.api.domain.errors import Conflict

__all__ = ["DecideRevision"]

#: The only status a revision can be decided from.
_PROPOSED = "proposed"

#: `plan_revisions.proposed_tasks` is written by the Plan Engine as
#: `[plan_patch, task, task, ...]` — see `services/plan_engine/domain/revision.py`
#: (`encode_proposal`). The patch carries the `plans` columns to write on accept; the rest
#: are `plan_tasks` rows. Services never import each other, so this JSON shape is the
#: contract between the two sides: change one, change the other.
_PATCH_FIELDS = ("goal_statement", "duration_weeks", "template", "structure")


class DecideRevision:
    """The user's answer to a proposal; nothing else may apply one."""

    def __init__(
        self,
        plans: PlanRepo,
        plan_tasks: PlanTaskRepo,
        revisions: PlanRevisionRepo,
        profiles: ProfileRepo,
        exports: PlanExportRepo,
        queue: QueuePort,
        clock: ClockPort,
        get_revision: GetRevision,
    ) -> None:
        self._plans = plans
        self._plan_tasks = plan_tasks
        self._revisions = revisions
        self._profiles = profiles
        self._exports = exports
        self._queue = queue
        self._clock = clock
        self._get_revision = get_revision

    async def __call__(
        self,
        user_id: UUID,
        plan_id: UUID,
        revision_id: UUID,
        decision: Literal["accept", "reject"],
    ) -> RevisionView:
        revision = await self._get_revision.load(user_id, plan_id, revision_id)
        if revision.status != _PROPOSED:
            raise Conflict(f"a {revision.status} revision cannot be {decision}ed")

        now = self._clock.now()
        if decision == "accept":
            await self._accept(user_id, plan_id, revision.proposed_tasks or [])
        status = "accepted" if decision == "accept" else "rejected"
        await self._revisions.set_status(revision_id, status, now)
        return revision_view(await self._get_revision.load(user_id, plan_id, revision_id))

    async def _accept(self, user_id: UUID, plan_id: UUID, proposal: list[dict[str, Any]]) -> None:
        if not proposal:
            raise Conflict("this revision carries no proposal")
        patch, *rows = proposal
        tasks = [NewPlanTask.model_validate(row) for row in rows]

        profile = await self._profiles.get(user_id)
        tz = resolve_timezone(profile.timezone if profile is not None else None)
        cutoff = _day_start(self._clock.now().astimezone(tz).date(), tz)

        await self._plan_tasks.replace_from(plan_id, cutoff, tasks)
        await self._plans.update_fields(
            plan_id,
            deadline=date.fromisoformat(str(patch["deadline"])),
            **{field: patch[field] for field in _PATCH_FIELDS},
        )
        await enqueue_incremental_export(self._exports, self._queue, plan_id)


def _day_start(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)
