"""Finish an upload: confirm the object landed, then queue it for parsing."""

from uuid import UUID

from packages.queue import ImportParseJobV1, QueuePort
from packages.repo import DocumentRepo, ImportRepo
from packages.storage import StoragePort
from services.api.application.list_imports import ImportView, to_view
from services.api.domain.errors import InvalidInput, NotFound

__all__ = ["CompleteImport"]

STATUS_QUEUED = "queued"


class CompleteImport:
    """Called by the client once it has PUT the file to the presigned URL."""

    def __init__(
        self,
        imports: ImportRepo,
        documents: DocumentRepo,
        storage: StoragePort,
        queue: QueuePort,
    ) -> None:
        self._imports = imports
        self._documents = documents
        self._storage = storage
        self._queue = queue

    async def __call__(self, user_id: UUID, import_id: UUID) -> ImportView:
        record = await self._imports.get(user_id, import_id)
        if record is None:
            raise NotFound(f"import not found: {import_id}")
        if not await self._storage.exists(record.storage_key):
            raise InvalidInput(f"no object was uploaded for import {import_id}")

        await self._imports.set_status(import_id, STATUS_QUEUED)
        await self._queue.enqueue(ImportParseJobV1(import_id=import_id))
        document = await self._documents.get_by_import(import_id)
        return to_view(record.model_copy(update={"status": STATUS_QUEUED}), document)
