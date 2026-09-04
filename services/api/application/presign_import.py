"""Start a file upload: validate it, create a pending import, and hand back a presigned URL."""

from uuid import UUID, uuid4

from pydantic import BaseModel

from packages.importers import UnsupportedFormat, detect_format
from packages.repo import ImportRepo
from packages.storage import StoragePort
from services.api.domain.errors import InvalidInput

__all__ = ["PresignImport", "PresignResult", "safe_filename"]

SOURCE_UPLOAD = "upload"


class PresignResult(BaseModel):
    import_id: UUID
    upload_url: str
    storage_key: str
    expires_in: int


def safe_filename(filename: str) -> str:
    """Reduce a client-supplied name to a single path segment with no `..`."""
    name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    name = name.replace("..", "").strip()
    if not name:
        raise InvalidInput("filename must not be empty")
    return name


class PresignImport:
    """Uploads are capped at 20 MB and must be a format one of our parsers understands."""

    MAX_BYTES = 20 * 1024 * 1024
    EXPIRES_IN = 900

    def __init__(self, imports: ImportRepo, storage: StoragePort) -> None:
        self._imports = imports
        self._storage = storage

    async def __call__(
        self, user_id: UUID, filename: str, content_type: str, size_bytes: int
    ) -> PresignResult:
        if size_bytes > self.MAX_BYTES:
            raise InvalidInput(f"file is larger than the 20 MB limit ({self.MAX_BYTES} bytes)")
        name = safe_filename(filename)
        try:
            fmt = detect_format(name, content_type)
        except UnsupportedFormat as exc:
            raise InvalidInput(str(exc)) from exc

        # `ImportRepo.create` mints the row id and offers no way to update the key afterwards,
        # so the key gets its own random segment instead of the import id.
        storage_key = f"imports/{user_id}/{uuid4()}/{name}"
        record = await self._imports.create(user_id, SOURCE_UPLOAD, fmt, storage_key, name)
        upload_url = await self._storage.presign_put(storage_key, content_type, self.EXPIRES_IN)
        return PresignResult(
            import_id=record.id,
            upload_url=upload_url,
            storage_key=storage_key,
            expires_in=self.EXPIRES_IN,
        )
