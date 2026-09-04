"""用 Google 授權碼登入，回一個本系統的 JWT。"""

from uuid import UUID

from pydantic import BaseModel

from packages.repo import ProfileRepo, UserRepo
from services.api.application.ports import GoogleOidcPort, TokenIssuerPort

__all__ = ["DEFAULT_TIMEZONE", "LoginResult", "LoginWithGoogle"]

DEFAULT_TIMEZONE = "UTC"


class LoginResult(BaseModel):
    access_token: str
    user_id: UUID
    email: str
    is_new_user: bool


class LoginWithGoogle:
    """首次登入建 user + 空 profile，之後沿用同一個 user。"""

    def __init__(
        self,
        users: UserRepo,
        profiles: ProfileRepo,
        oidc: GoogleOidcPort,
        tokens: TokenIssuerPort,
    ) -> None:
        self._users = users
        self._profiles = profiles
        self._oidc = oidc
        self._tokens = tokens

    async def __call__(self, code: str, redirect_uri: str) -> LoginResult:
        identity = await self._oidc.exchange_code(code, redirect_uri)
        user = await self._users.get_by_google_sub(identity.google_sub)
        is_new_user = user is None
        if user is None:
            user = await self._users.create(identity.email, identity.google_sub)
            await self._profiles.upsert(user.id, {}, DEFAULT_TIMEZONE)
        return LoginResult(
            access_token=self._tokens.issue(user.id),
            user_id=user.id,
            email=user.email,
            is_new_user=is_new_user,
        )
