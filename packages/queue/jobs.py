"""Versioned queue payloads. Every payload knows which queue it belongs to."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

__all__ = [
    "JOB_REGISTRY",
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
