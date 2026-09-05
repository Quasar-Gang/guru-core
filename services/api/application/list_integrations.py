"""List a user's third-party connections, and the view model every integration endpoint returns."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from packages.repo import OAuthConnectionRepo
from packages.repo.entities import OAuthConnection

__all__ = ["IntegrationView", "ListIntegrations", "to_view"]


class IntegrationView(BaseModel):
    """One provider connection as seen by the API client."""

    provider: str
    connected: bool
    scopes: list[str]
    needs_reauth: bool
    connected_at: datetime | None


def to_view(connection: OAuthConnection) -> IntegrationView:
    """A revoked connection stays in the list so the client can prompt for a reconnect."""
    revoked = connection.revoked_at is not None
    return IntegrationView(
        provider=connection.provider,
        connected=not revoked,
        scopes=connection.scopes.split(),
        needs_reauth=revoked,
        connected_at=connection.created_at,
    )


class ListIntegrations:
    """Every connection row belonging to one user."""

    def __init__(self, oauth_connections: OAuthConnectionRepo) -> None:
        self._oauth_connections = oauth_connections

    async def __call__(self, user_id: UUID) -> list[IntegrationView]:
        return [to_view(c) for c in await self._oauth_connections.list_for_user(user_id)]
