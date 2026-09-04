"""Queue adapter: widen `ParseImport` to the generic handler signature the worker expects."""

from packages.logging import bind_job_id
from packages.queue import ImportParseJobV1, JobPayload
from services.api.application.parse_import import ParseImport

__all__ = ["ImportParseConsumer"]


class ImportParseConsumer:
    """Validate that the payload really is an `import.parse` job, then delegate."""

    def __init__(self, parse_import: ParseImport) -> None:
        self._parse_import = parse_import

    async def __call__(self, payload: JobPayload) -> None:
        if not isinstance(payload, ImportParseJobV1):
            raise TypeError(f"expected ImportParseJobV1, got {type(payload).__name__}")
        with bind_job_id(str(payload.import_id)):
            await self._parse_import(payload)
