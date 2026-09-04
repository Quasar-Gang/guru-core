"""Request and response models at the HTTP boundary (all Pydantic v2)."""

from uuid import UUID

from pydantic import BaseModel

__all__ = ["ErrorBody", "ErrorResponse", "GoogleLoginRequest", "LoginResponse", "MeResponse"]


class GoogleLoginRequest(BaseModel):
    code: str
    redirect_uri: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: UUID
    email: str
    is_new_user: bool


class MeResponse(BaseModel):
    user_id: UUID
    email: str


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody
