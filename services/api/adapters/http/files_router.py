"""Presigned upload/download endpoints backing `LocalFileStorage`.

These two routes carry their own authorization in the query string (`exp`/`op`/`sig`), so
unlike every other route they take no bearer token.
"""

from fastapi import APIRouter, Request, Response

from packages.storage import LocalFileStorage, ObjectNotFound
from services.api.adapters.http.deps import get_container
from services.api.domain.errors import Forbidden, NotFound

__all__ = ["router"]

router = APIRouter(tags=["files"])

DEFAULT_CONTENT_TYPE = "application/octet-stream"


def _authorize(request: Request, expected_op: str, key: str, exp: int, op: str, sig: str) -> None:
    """Reject anything whose signature does not cover exactly this operation, key and expiry."""
    container = get_container(request)
    signed_for_this_op = op == expected_op
    valid = LocalFileStorage.verify_signature(
        container.settings.storage_signing_secret, op, key, exp, sig, container.clock.now()
    )
    if not (signed_for_this_op and valid):
        raise Forbidden("invalid or expired signature")


@router.put("/files/{key:path}", status_code=200)
async def upload_file(request: Request, key: str, exp: int, op: str, sig: str) -> Response:
    _authorize(request, "put", key, exp, op, sig)
    data = await request.body()
    content_type = request.headers.get("Content-Type") or DEFAULT_CONTENT_TYPE
    await get_container(request).storage.put(key, data, content_type)
    return Response(status_code=200)


@router.get("/files/{key:path}")
async def download_file(request: Request, key: str, exp: int, op: str, sig: str) -> Response:
    _authorize(request, "get", key, exp, op, sig)
    try:
        data = await get_container(request).storage.get(key)
    except ObjectNotFound as exc:
        raise NotFound(f"object not found: {key}") from exc
    return Response(content=data, media_type=DEFAULT_CONTENT_TYPE)
