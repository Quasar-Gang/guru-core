"""LocalFileStorage — production implementation backed by a local directory.

Presigned URLs point at the local API and carry an HMAC signature.
"""

import hashlib
import hmac
import json
from datetime import UTC, datetime
from pathlib import Path

from packages.storage.ports import ObjectNotFound, StoredObject

_META_SUFFIX = ".meta"


class LocalFileStorage:
    """StoragePort implementation that writes objects under `root`.

    The content type is kept in a JSON sidecar next to the object, suffixed with `.meta`.
    """

    def __init__(self, root: Path, public_base_url: str, signing_secret: str) -> None:
        self._root = Path(root).resolve()
        self._public_base_url = public_base_url.rstrip("/")
        self._signing_secret = signing_secret

    def _resolve(self, key: str) -> Path:
        """Resolve a key to a path under root, rejecting absolute paths and `..`."""
        if not key:
            raise ValueError("key must not be empty")
        candidate = Path(key)
        if candidate.is_absolute():
            raise ValueError(f"key must be relative: {key!r}")
        if ".." in candidate.parts:
            raise ValueError(f"key must not contain '..': {key!r}")
        return self._root / candidate

    async def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        meta_path = path.with_name(path.name + _META_SUFFIX)
        meta_path.write_text(json.dumps({"content_type": content_type}), encoding="utf-8")
        return StoredObject(key=key, size=len(data), content_type=content_type)

    async def get(self, key: str) -> bytes:
        path = self._resolve(key)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise ObjectNotFound(key) from exc

    async def delete(self, key: str) -> None:
        path = self._resolve(key)
        path.unlink(missing_ok=True)
        path.with_name(path.name + _META_SUFFIX).unlink(missing_ok=True)

    async def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()

    async def presign_put(self, key: str, content_type: str, expires_in: int) -> str:
        return self._presign("put", key, expires_in)

    async def presign_get(self, key: str, expires_in: int) -> str:
        return self._presign("get", key, expires_in)

    def _presign(self, op: str, key: str, expires_in: int) -> str:
        self._resolve(key)
        exp = int(datetime.now(UTC).timestamp()) + expires_in
        sig = _sign(self._signing_secret, op, key, exp)
        return f"{self._public_base_url}/{key}?exp={exp}&op={op}&sig={sig}"

    @staticmethod
    def verify_signature(secret: str, op: str, key: str, exp: int, sig: str, now: datetime) -> bool:
        """Return True when the signature matches and has not expired."""
        if int(now.timestamp()) > exp:
            return False
        return hmac.compare_digest(_sign(secret, op, key, exp), sig)


def _sign(secret: str, op: str, key: str, exp: int) -> str:
    message = f"{op}:{key}:{exp}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
