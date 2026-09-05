"""Versioned queue payloads. Every payload knows which queue it belongs to.

Everything past the upload is asynchronous and polled by the client, with PostgreSQL as the
authoritative state and Redis only as a cache. These five payloads are the whole pipeline:

    import.parse   -> a Document                (API worker)
    profile.build  -> the Profile               (Engine)
    direction.run  -> Reports, then Fit Verdicts (Engine)
    plan.generate  -> Milestones, Tasks, Schedule (Engine)
    reconcile.run  -> a Reconciliation           (Engine)
    export.push    -> the Schedule on a calendar (API worker)
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

__all__ = [
    "API_WORKER_QUEUE",
    "ENGINE_WORKER_QUEUE",
    "JOB_REGISTRY",
    "WORKER_QUEUE_BY_JOB",
    "DirectionRunJobV1",
    "ExportJobV1",
    "ImportParseJobV1",
    "JobPayload",
    "PlanGenerateJobV1",
    "ProfileBuildJobV1",
    "ReconcileJobV1",
]


class JobPayload(BaseModel):
    """Base class for every queue payload: immutable and strict."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    @classmethod
    def queue_name(cls) -> str:
        raise NotImplementedError


class ImportParseJobV1(JobPayload):
    import_id: UUID

    @classmethod
    def queue_name(cls) -> str:
        return "import.parse"


class ProfileBuildJobV1(JobPayload):
    user_id: UUID

    @classmethod
    def queue_name(cls) -> str:
        return "profile.build"


class DirectionRunJobV1(JobPayload):
    run_id: UUID

    @classmethod
    def queue_name(cls) -> str:
        return "direction.run"


class PlanGenerateJobV1(JobPayload):
    plan_id: UUID

    @classmethod
    def queue_name(cls) -> str:
        return "plan.generate"


class ReconcileJobV1(JobPayload):
    reconciliation_id: UUID

    @classmethod
    def queue_name(cls) -> str:
        return "reconcile.run"


class ExportJobV1(JobPayload):
    plan_id: UUID
    target: Literal["google_calendar"]
    mode: Literal["full", "incremental"]

    @classmethod
    def queue_name(cls) -> str:
        return "export.push"


JOB_REGISTRY: dict[str, type[JobPayload]] = {
    cls.queue_name(): cls
    for cls in (
        ImportParseJobV1,
        ProfileBuildJobV1,
        DirectionRunJobV1,
        PlanGenerateJobV1,
        ReconcileJobV1,
        ExportJobV1,
    )
}


#: Redis lists the workers poll. Two workers share one Redis, so they must not poll the
#: same list: whoever pops a job first tries to run it, and a worker that has no handler for
#: that job discards it with `JobExecutionFailed: function not found`. One list per
#: deployable is what keeps `import.parse` and `direction.run` independent.
API_WORKER_QUEUE = "arq:queue:api"
ENGINE_WORKER_QUEUE = "arq:queue:engine"

WORKER_QUEUE_BY_JOB: dict[str, str] = {
    ImportParseJobV1.queue_name(): API_WORKER_QUEUE,
    ExportJobV1.queue_name(): API_WORKER_QUEUE,
    ProfileBuildJobV1.queue_name(): ENGINE_WORKER_QUEUE,
    DirectionRunJobV1.queue_name(): ENGINE_WORKER_QUEUE,
    PlanGenerateJobV1.queue_name(): ENGINE_WORKER_QUEUE,
    ReconcileJobV1.queue_name(): ENGINE_WORKER_QUEUE,
}
