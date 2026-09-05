"""Queue adapter: widen `PushExport` to the generic handler signature the worker expects."""

from packages.logging import bind_job_id
from packages.queue import ExportJobV1, JobPayload
from services.api.application.exports import PushExport

__all__ = ["ExportPushConsumer"]


class ExportPushConsumer:
    """Validate that the payload really is an `export.push` job, then delegate."""

    def __init__(self, push_export: PushExport) -> None:
        self._push_export = push_export

    async def __call__(self, payload: JobPayload) -> None:
        if not isinstance(payload, ExportJobV1):
            raise TypeError(f"expected ExportJobV1, got {type(payload).__name__}")
        with bind_job_id(str(payload.plan_id)):
            await self._push_export(payload)
