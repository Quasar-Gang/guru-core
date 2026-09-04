"""HTTP 邊界的請求／回應 model（跨邊界資料一律 Pydantic）。"""

from typing import Any

from pydantic import BaseModel, Field


class UpsertRoleModelRequest(BaseModel):
    """`POST /role-models` 與 `PUT /role-models/{id}` 的 body。"""

    kind: str
    name: str = Field(min_length=1)
    tags: list[str] = []
    content: dict[str, Any] = {}


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
