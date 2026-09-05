"""Presigned upload/download endpoints backing `LocalFileStorage`.

These two routes carry their own authorization in the query string (`exp`/`op`/`sig`), so
unlike every other route they take no bearer token.
"""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response

from packages.storage import LocalFileStorage, ObjectNotFound
from services.api.adapters.http.deps import get_container
from services.api.adapters.http.schemas import ErrorResponse
from services.api.domain.errors import Forbidden, NotFound

__all__ = ["router"]

router = APIRouter(tags=["files"])

DEFAULT_CONTENT_TYPE = "application/octet-stream"

_FORBIDDEN = {
    "model": ErrorResponse,
    "description": (
        "`forbidden` — the signature does not match, was minted for the other operation "
        "(a `get` URL cannot be used to `put`), or `exp` has passed. Presigned URLs live "
        "for 15 minutes; ask for a new one rather than editing the query string."
    ),
}


def _authorize(request: Request, expected_op: str, key: str, exp: int, op: str, sig: str) -> None:
    """Reject anything whose signature does not cover exactly this operation, key and expiry."""
    container = get_container(request)
    signed_for_this_op = op == expected_op
    valid = LocalFileStorage.verify_signature(
        container.settings.storage_signing_secret, op, key, exp, sig, container.clock.now()
    )
    if not (signed_for_this_op and valid):
        raise Forbidden("invalid or expired signature")


@router.put(
    "/files/{key:path}",
    status_code=200,
    summary="Upload bytes to a presigned URL (step 2 of a file import)",
    response_description="Empty body. The object is stored; nothing is parsed yet.",
    responses={
        200: {"description": "Stored. The response body is empty."},
        403: _FORBIDDEN,
    },
)
async def upload_file(
    request: Request,
    key: Annotated[str, Path(description="Storage key, as embedded in the presigned URL.")],
    exp: Annotated[int, Query(description="Unix timestamp after which the signature is refused.")],
    op: Annotated[
        str, Query(description="Operation the signature was minted for; must be `put` here.")
    ],
    sig: Annotated[str, Query(description="HMAC signature over `op`, `key` and `exp`.")],
) -> Response:
    """The destination of the `upload_url` returned by `POST /v1/imports/presign`.

    **Do not construct this URL yourself.** Take `upload_url` verbatim, query string and
    all, and `PUT` the raw file bytes to it — no multipart wrapper, no JSON envelope.

    Authorization comes entirely from the `exp`/`op`/`sig` query parameters, which are
    signed for exactly this key, this operation and this expiry; send **no**
    `Authorization` header. The URL is good for 15 minutes and this route is exempt from
    the per-minute rate limit, so a large upload cannot spend the user's request budget.

    Send the same `Content-Type` you declared at presign time; it is stored alongside the
    object. A missing header falls back to `application/octet-stream`. The 20 MB limit was
    already enforced at presign, so it is not re-checked here.

    A `200` only means the bytes landed. The import stays `pending` until you call
    `POST /v1/imports/{import_id}/complete`.

    This route exists for the local storage backend; in a deployment backed by object
    storage the presigned URL points at the bucket instead. Either way the client code is
    the same: PUT to whatever `upload_url` says.
    """
    _authorize(request, "put", key, exp, op, sig)
    data = await request.body()
    content_type = request.headers.get("Content-Type") or DEFAULT_CONTENT_TYPE
    await get_container(request).storage.put(key, data, content_type)
    return Response(status_code=200)


@router.get(
    "/files/{key:path}",
    summary="Download bytes from a presigned URL",
    response_description="The raw object bytes, served as `application/octet-stream`.",
    responses={
        200: {
            "content": {"application/octet-stream": {}},
            "description": "The object's bytes.",
        },
        403: _FORBIDDEN,
        404: {
            "model": ErrorResponse,
            "description": (
                "`not_found` — the signature is valid but no object exists at that key: it "
                "was never uploaded, or has since been deleted."
            ),
        },
    },
)
async def download_file(
    request: Request,
    key: Annotated[str, Path(description="Storage key, as embedded in the presigned URL.")],
    exp: Annotated[int, Query(description="Unix timestamp after which the signature is refused.")],
    op: Annotated[
        str, Query(description="Operation the signature was minted for; must be `get` here.")
    ],
    sig: Annotated[str, Query(description="HMAC signature over `op`, `key` and `exp`.")],
) -> Response:
    """Read back an object through a download URL the backend handed out.

    Same rules as the upload route: use the URL exactly as given, send no bearer token,
    and expect it to stop working 15 minutes after it was minted. The signature covers the
    `get` operation specifically, so an upload URL cannot be replayed as a download.

    The body is always served as `application/octet-stream` regardless of the type the
    object was stored with, so treat it as a binary download rather than something to
    render inline. Like the upload route, it is exempt from the per-minute rate limit.
    """
    _authorize(request, "get", key, exp, op, sig)
    try:
        data = await get_container(request).storage.get(key)
    except ObjectNotFound as exc:
        raise NotFound(f"object not found: {key}") from exc
    return Response(content=data, media_type=DEFAULT_CONTENT_TYPE)
