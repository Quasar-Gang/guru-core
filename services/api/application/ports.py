"""Ports (Protocols) and cross-boundary data types for the API service application layer.

Implementations of these ports live in `services/api/adapters/`. Use cases depend only on
the Protocols defined here and on the ports from `packages/*`, and never see fastapi, httpx,
or SDK types.
"""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel

__all__ = ["ClockPort", "GoogleIdentity", "GoogleOidcPort", "TokenIssuerPort"]


class GoogleIdentity(BaseModel):
    """Identity returned by a Google login."""

    google_sub: str
    email: str


class GoogleOidcPort(Protocol):
    """Exchange an authorization code for a Google identity (login only; openid email profile)."""

    async def exchange_code(self, code: str, redirect_uri: str) -> GoogleIdentity: ...


class TokenIssuerPort(Protocol):
    """Issue and verify our own access tokens."""

    def issue(self, user_id: UUID) -> str: ...

    def verify(self, token: str) -> UUID:
        """Raise `Unauthorized` on any failure: expired, bad signature, or malformed."""
        ...


class ClockPort(Protocol):
    """Current time; always timezone-aware UTC."""

    def now(self) -> datetime: ...
