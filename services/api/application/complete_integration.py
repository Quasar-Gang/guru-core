"""Exchange the OAuth code for tokens and store the refresh token encrypted."""

from uuid import UUID

from packages.repo import OAuthConnectionRepo
from services.api.application.authorize_integration import assert_supported
from services.api.application.list_integrations import IntegrationView, to_view
from services.api.application.ports import GoogleOAuthPort, TokenCipherPort
from services.api.domain.errors import InvalidInput

__all__ = ["CompleteIntegration"]


class CompleteIntegration:
    """Called by the client with the `code` Google redirected back to it."""

    def __init__(
        self,
        oauth_connections: OAuthConnectionRepo,
        oauth: GoogleOAuthPort,
        cipher: TokenCipherPort,
    ) -> None:
        self._oauth_connections = oauth_connections
        self._oauth = oauth
        self._cipher = cipher

    async def __call__(self, user_id: UUID, provider: str, code: str) -> IntegrationView:
        assert_supported(provider)
        tokens = await self._oauth.exchange_code(code)
        if not tokens.refresh_token:
            # Without a refresh token every later worker call would need the user present.
            raise InvalidInput("google did not return a refresh token; retry the consent flow")
        connection = await self._oauth_connections.upsert(
            user_id,
            provider,
            self._cipher.encrypt(tokens.refresh_token),
            " ".join(tokens.scopes),
            tokens.expires_at,
        )
        return to_view(connection)
