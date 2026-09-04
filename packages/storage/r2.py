"""R2Storage — StoragePort implementation backed by Cloudflare R2 (S3-compatible).

This is the only module in the codebase allowed to import `boto3`. Every boto3 call is
synchronous, so each one runs in `asyncio.to_thread` to keep the port truly async.
"""

import asyncio
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from packages.storage.ports import ObjectNotFound, StoredObject

_NOT_FOUND_CODES = frozenset({"NoSuchKey", "NotFound", "404"})


class R2Storage:
    """StoragePort implementation that stores objects in a Cloudflare R2 bucket.

    The endpoint is `endpoint_url` when given, otherwise the account's R2 endpoint
    (`https://{account_id}.r2.cloudflarestorage.com`). With neither, boto3 falls back to its
    own default endpoint, which is what lets an in-process S3 mock intercept the calls in
    tests.
    """

    def __init__(
        self,
        *,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        endpoint_url: str | None = None,
    ) -> None:
        self._bucket = bucket
        if endpoint_url is None and account_id:
            endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )

    async def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return StoredObject(key=key, size=len(data), content_type=content_type)

    async def get(self, key: str) -> bytes:
        try:
            response = await asyncio.to_thread(
                self._client.get_object, Bucket=self._bucket, Key=key
            )
        except ClientError as exc:
            if _is_not_found(exc):
                raise ObjectNotFound(key) from exc
            raise
        body: bytes = await asyncio.to_thread(response["Body"].read)
        return body

    async def delete(self, key: str) -> None:
        # S3 `DeleteObject` already succeeds for a key that does not exist.
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)

    async def exists(self, key: str) -> bool:
        try:
            await asyncio.to_thread(self._client.head_object, Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if _is_not_found(exc):
                return False
            raise
        return True

    async def presign_put(self, key: str, content_type: str, expires_in: int) -> str:
        url: str = await asyncio.to_thread(
            self._client.generate_presigned_url,
            "put_object",
            Params={"Bucket": self._bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expires_in,
        )
        return url

    async def presign_get(self, key: str, expires_in: int) -> str:
        url: str = await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        return url


def _is_not_found(exc: ClientError) -> bool:
    """Return True when a boto3 error means "this key is not in the bucket"."""
    response: dict[str, Any] = exc.response  # type: ignore[assignment]
    code = str(response.get("Error", {}).get("Code", ""))
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in _NOT_FOUND_CODES or status == 404
