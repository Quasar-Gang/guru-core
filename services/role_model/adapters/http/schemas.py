"""Request and response models for the HTTP boundary (all boundary data is Pydantic)."""

from typing import Any

from pydantic import BaseModel, Field


class UpsertRoleModelRequest(BaseModel):
    """Body of `POST /role-models` and `PUT /role-models/{id}`."""

    kind: str
    name: str = Field(min_length=1)
    tags: list[str] = []
    content: dict[str, Any] = {}


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
