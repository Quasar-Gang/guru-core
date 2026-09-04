"""Turn a stored refresh token into a usable Google access token, cached until it expires."""

from uuid import UUID

from packages.cache import CachePort
from packages.repo import OAuthConnectionRepo
from services.api.application.authorize_integration import GOOGLE_PROVIDER
from services.api.application.ports import ClockPort, GoogleOAuthPort, InvalidGrant, TokenCipherPort
from services.api.domain.errors import ReauthRequired

__all__ = ["GOOGLE_TOKEN_CACHE_PREFIX", "GoogleAccessTokenProvider"]

GOOGLE_TOKEN_CACHE_PREFIX = "gtok:"

#: Stop using a cached token a minute before Google would reject it.
EXPIRY_MARGIN_SECONDS = 60


class GoogleAccessTokenProvider:
    """The single place any Google call gets its access token from.

    Redis is a cache only: losing it costs one extra refresh round trip, never a connection.
    """

    def __init__(
        self,
        oauth_repo: OAuthConnectionRepo,
        oauth: GoogleOAuthPort,
        cipher: TokenCipherPort,
        cache: CachePort,
        clock: ClockPort,
    ) -> None:
        self._oauth_repo = oauth_repo
        self._oauth = oauth
        self._cipher = cipher
        self._cache = cache
        self._clock = clock

    def cache_key(self, user_id: UUID) -> str:
        return f"{GOOGLE_TOKEN_CACHE_PREFIX}{user_id}"

    async def get(self, user_id: UUID) -> str:
        cached = await self._cache.get(self.cache_key(user_id))
        if cached:
            return cached

        connection = await self._oauth_repo.get(user_id, GOOGLE_PROVIDER)
        if connection is None or connection.revoked_at is not None:
            raise ReauthRequired("google is not connected; reconnect to continue")

        refresh_token = self._cipher.decrypt(connection.encrypted_refresh_token)
        try:
            tokens = await self._oauth.refresh(refresh_token)
        except InvalidGrant as exc:
            await self._oauth_repo.mark_revoked(user_id, GOOGLE_PROVIDER, self._clock.now())
            raise ReauthRequired("google authorization expired; reconnect to continue") from exc

        if tokens.expires_at is not None:
            ttl = (
                int((tokens.expires_at - self._clock.now()).total_seconds()) - EXPIRY_MARGIN_SECONDS
            )
            if ttl > 0:
                await self._cache.set(self.cache_key(user_id), tokens.access_token, ttl)
        return tokens.access_token
