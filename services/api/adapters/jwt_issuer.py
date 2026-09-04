"""TokenIssuerPort 的 HMAC-SHA256 JWT 實作。"""

from uuid import UUID

import jwt

from services.api.application.ports import ClockPort
from services.api.domain.errors import Unauthorized

__all__ = ["ALGORITHM", "HmacTokenIssuer"]

ALGORITHM = "HS256"


class HmacTokenIssuer:
    """簽發 `{sub, iat, exp}` 的 HS256 JWT。

    過期判斷用注入的 `clock`（而不是 pyjwt 的系統時間），這樣 `FakeClock`
    才能在測試裡把時間推前。
    """

    def __init__(self, secret: str, ttl_seconds: int, clock: ClockPort) -> None:
        self._secret = secret
        self._ttl_seconds = ttl_seconds
        self._clock = clock

    def issue(self, user_id: UUID) -> str:
        issued_at = int(self._clock.now().timestamp())
        return jwt.encode(
            {"sub": str(user_id), "iat": issued_at, "exp": issued_at + self._ttl_seconds},
            self._secret,
            algorithm=ALGORITHM,
        )

    def verify(self, token: str) -> UUID:
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=[ALGORITHM],
                options={"verify_exp": False, "require": ["sub", "exp"]},
            )
        except jwt.PyJWTError as exc:
            raise Unauthorized("invalid token") from exc

        expires_at = claims.get("exp")
        if not isinstance(expires_at, int | float):
            raise Unauthorized("invalid token")
        if self._clock.now().timestamp() >= expires_at:
            raise Unauthorized("token expired")

        try:
            return UUID(str(claims["sub"]))
        except ValueError as exc:
            raise Unauthorized("invalid token subject") from exc
