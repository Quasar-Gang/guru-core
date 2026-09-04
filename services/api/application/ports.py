"""Ports (Protocols) and cross-boundary data types for the API service application layer.

Implementations of these ports live in `services/api/adapters/`. Use cases depend only on
the Protocols defined here and on the ports from `packages/*`, and never see fastapi, httpx,
or SDK types.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, Field

__all__ = [
    "CalendarEvent",
    "CalendarEventWrite",
    "CalendarPort",
    "ClockPort",
    "GoogleIdentity",
    "GoogleOAuthPort",
    "GoogleOidcPort",
    "InvalidGrant",
    "OAuthTokens",
    "TokenCipherPort",
    "TokenIssuerPort",
]


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


class InvalidGrant(Exception):
    """Google rejected the refresh token (`invalid_grant`); the grant is gone for good.

    Raised by `GoogleOAuthPort` implementations. Use cases translate it into the domain
    error `ReauthRequired` after recording the revocation.
    """


class OAuthTokens(BaseModel):
    """The result of an authorization-code exchange or a refresh."""

    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scopes: list[str]


class GoogleOAuthPort(Protocol):
    """Full Google OAuth (not login): calendar and spreadsheets access on the user's behalf."""

    def authorize_url(self, state: str, scopes: Sequence[str]) -> str: ...

    async def exchange_code(self, code: str) -> OAuthTokens: ...

    async def refresh(self, refresh_token: str) -> OAuthTokens:
        """Raise `InvalidGrant` when Google says the refresh token is no longer valid."""
        ...

    async def revoke(self, refresh_token: str) -> None:
        """Best effort: an already-revoked token must not make disconnecting fail."""
        ...


class CalendarEvent(BaseModel):
    """One event read from the user's calendar."""

    external_id: str
    summary: str
    start_at: datetime
    end_at: datetime
    all_day: bool


class CalendarEventWrite(BaseModel):
    """One event we write to the user's calendar."""

    summary: str
    description: str
    start_at: datetime
    end_at: datetime
    all_day: bool
    color_id: str | None = None
    private_props: dict[str, str] = Field(default_factory=dict)


class CalendarPort(Protocol):
    """Read and write a Google calendar with an already-refreshed access token."""

    async def list_events(
        self, access_token: str, time_min: datetime, time_max: datetime
    ) -> list[CalendarEvent]: ...

    async def create_calendar(self, access_token: str, summary: str) -> str: ...

    async def create_event(
        self, access_token: str, calendar_id: str, event: CalendarEventWrite
    ) -> str: ...

    async def update_event(
        self, access_token: str, calendar_id: str, event_id: str, event: CalendarEventWrite
    ) -> None: ...

    async def delete_event(self, access_token: str, calendar_id: str, event_id: str) -> None: ...

    async def delete_calendar(self, access_token: str, calendar_id: str) -> None: ...


class TokenCipherPort(Protocol):
    """Encrypt refresh tokens at rest; they never leave the backend in plaintext."""

    def encrypt(self, plaintext: str) -> bytes: ...

    def decrypt(self, ciphertext: bytes) -> str: ...
