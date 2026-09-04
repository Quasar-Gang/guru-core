"""Versioned queue payloads. Every payload knows which queue it belongs to."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

__all__ = [
    "API_WORKER_QUEUE",
    "JOB_REGISTRY",
    "PLAN_ENGINE_WORKER_QUEUE",
    "WORKER_QUEUE_BY_JOB",
    "ExportJobV1",
    "ImportParseJobV1",
    "JobPayload",
    "PlanContinueJobV1",
    "PlanGenerateJobV1",
    "PlanReviseJobV1",
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


class PlanGenerateJobV1(JobPayload):
    session_id: UUID

    @classmethod
    def queue_name(cls) -> str:
        return "plan.generate"


class PlanContinueJobV1(JobPayload):
    session_id: UUID

    @classmethod
    def queue_name(cls) -> str:
        return "plan.continue"


class PlanReviseJobV1(JobPayload):
    plan_id: UUID
    revision_id: UUID
    strategy: Literal["postpone", "reduce"]

    @classmethod
    def queue_name(cls) -> str:
        return "plan.revise"


class ExportJobV1(JobPayload):
    plan_id: UUID
    target: Literal["google_calendar", "google_sheets", "notion"]
    mode: Literal["full", "incremental"]

    @classmethod
    def queue_name(cls) -> str:
        return "export.push"


JOB_REGISTRY: dict[str, type[JobPayload]] = {
    cls.queue_name(): cls
    for cls in (
        ImportParseJobV1,
        PlanGenerateJobV1,
        PlanContinueJobV1,
        PlanReviseJobV1,
        ExportJobV1,
    )
}


#: Redis lists the workers poll. Two workers share one Redis, so they must not poll the
#: same list: whoever pops a job first tries to run it, and a worker that has no handler
#: for that job discards it with `JobExecutionFailed: function not found`. Keeping one
#: list per deployable is what makes `import.parse` and `plan.generate` independent.
API_WORKER_QUEUE = "arq:queue:api"
PLAN_ENGINE_WORKER_QUEUE = "arq:queue:plan-engine"

WORKER_QUEUE_BY_JOB: dict[str, str] = {
    ImportParseJobV1.queue_name(): API_WORKER_QUEUE,
    ExportJobV1.queue_name(): API_WORKER_QUEUE,
    PlanGenerateJobV1.queue_name(): PLAN_ENGINE_WORKER_QUEUE,
    PlanContinueJobV1.queue_name(): PLAN_ENGINE_WORKER_QUEUE,
    PlanReviseJobV1.queue_name(): PLAN_ENGINE_WORKER_QUEUE,
}
