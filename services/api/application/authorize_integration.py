"""Hand the client the Google consent URL for calendar access."""

from secrets import token_urlsafe
from uuid import UUID

from services.api.application.ports import GoogleOAuthPort
from services.api.domain.errors import InvalidInput

__all__ = ["CALENDAR_SCOPES", "GOOGLE_PROVIDER", "AuthorizeIntegration"]

GOOGLE_PROVIDER = "google"

#: One consent covers reading the user's calendar and writing the plan's own back to it.
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/spreadsheets",
]


def assert_supported(provider: str) -> None:
    """Google is the only provider with an OAuth integration in the MVP."""
    if provider != GOOGLE_PROVIDER:
        raise InvalidInput(f"unsupported integration provider: {provider}")


class AuthorizeIntegration:
    """Build the authorize URL. The `state` is an opaque nonce the client echoes back."""

    def __init__(self, oauth: GoogleOAuthPort) -> None:
        self._oauth = oauth

    async def __call__(self, user_id: UUID, provider: str) -> str:
        assert_supported(provider)
        # The callback endpoint is authenticated with our own JWT, so `state` only has to be
        # unguessable; it never needs to carry the user id.
        return self._oauth.authorize_url(token_urlsafe(24), CALENDAR_SCOPES)
