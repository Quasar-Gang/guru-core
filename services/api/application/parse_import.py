"""Worker handler: turn an uploaded blob into a Document.

This never raises. Anything that goes wrong is recorded on the import row as `failed`,
because a queue retry would hit the very same bad file again.
"""

from packages.importers import ParserRegistry, RawBlob
from packages.queue import ImportParseJobV1, ProfileBuildJobV1, QueuePort
from packages.repo import DocumentRepo, ImportRepo
from packages.storage import StoragePort

__all__ = ["ParseImport"]

STATUS_FAILED = "failed"
STATUS_PARSED = "parsed"


class ParseImport:
    """Read the blob, parse it, store the document, and move the import to a final status."""

    def __init__(
        self,
        imports: ImportRepo,
        documents: DocumentRepo,
        storage: StoragePort,
        registry: ParserRegistry,
        queue: QueuePort,
    ) -> None:
        self._imports = imports
        self._documents = documents
        self._storage = storage
        self._registry = registry
        self._queue = queue

    async def __call__(self, job: ImportParseJobV1) -> None:
        user_id = None
        try:
            record = await self._imports.get_unscoped(job.import_id)
            if record is None:
                return
            user_id = record.user_id
            data = await self._storage.get(record.storage_key)
            # The format was decided at presign time; re-state it as an extension so the
            # registry cannot pick a different parser than the one the row promises.
            filename = _filename_for(record.filename, record.format)
            document = self._registry.parse(RawBlob(data=data, content_type="", filename=filename))
            await self._documents.create(
                job.import_id,
                [e.model_dump(mode="json") for e in document.events],
                [c.model_dump(mode="json") for c in document.text_chunks],
            )
        except Exception as exc:  # noqa: BLE001 - a worker handler must not propagate
            await self._imports.set_status(
                job.import_id, STATUS_FAILED, error=str(exc) or repr(exc)
            )
            return
        await self._imports.set_status(job.import_id, STATUS_PARSED)
        # New data means the read of this person has changed, and the Profile is revised in
        # place rather than duplicated — so a rebuild is always the right response.
        if user_id is not None:
            await self._queue.enqueue(ProfileBuildJobV1(user_id=user_id))


def _filename_for(filename: str, fmt: str) -> str:
    return filename if filename.lower().endswith(f".{fmt}") else f"{filename}.{fmt}"
