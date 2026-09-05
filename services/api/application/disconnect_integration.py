"""Disconnect a provider: revoke the token upstream and mark the row revoked."""

from uuid import UUID

from packages.cache import CachePort
from packages.repo import OAuthConnectionRepo
from services.api.application.authorize_integration import assert_supported
from services.api.application.google_access_token import GOOGLE_TOKEN_CACHE_PREFIX
from services.api.application.ports import ClockPort, GoogleOAuthPort, TokenCipherPort
from services.api.domain.errors import NotFound

__all__ = ["DisconnectIntegration"]


class DisconnectIntegration:
    """The row is kept (with `revoked_at` set) so the client can still see it needs a reconnect."""

    def __init__(
        self,
        oauth_connections: OAuthConnectionRepo,
        oauth: GoogleOAuthPort,
        cipher: TokenCipherPort,
        cache: CachePort,
        clock: ClockPort,
    ) -> None:
        self._oauth_connections = oauth_connections
        self._oauth = oauth
        self._cipher = cipher
        self._cache = cache
        self._clock = clock

    async def __call__(self, user_id: UUID, provider: str) -> None:
        assert_supported(provider)
        connection = await self._oauth_connections.get(user_id, provider)
        if connection is None:
            raise NotFound(f"no {provider} connection to disconnect")
        if connection.revoked_at is None:
            await self._oauth.revoke(self._cipher.decrypt(connection.encrypted_refresh_token))
            await self._oauth_connections.mark_revoked(user_id, provider, self._clock.now())
        await self._cache.delete(f"{GOOGLE_TOKEN_CACHE_PREFIX}{user_id}")
