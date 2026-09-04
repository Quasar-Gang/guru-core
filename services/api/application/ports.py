"""API Service application 層的 port（Protocol）與跨邊界資料型別。

這些 port 的實作住在 `services/api/adapters/`。use case 只認這裡的 Protocol
與 `packages/*` 的 port，永遠看不到 fastapi / httpx / SDK 型別。
"""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel

__all__ = ["ClockPort", "GoogleIdentity", "GoogleOidcPort", "TokenIssuerPort"]


class GoogleIdentity(BaseModel):
    """Google 登入回來的身分。"""

    google_sub: str
    email: str


class GoogleOidcPort(Protocol):
    """用授權碼換 Google 身分（登入用，scope 只有 openid email profile）。"""

    async def exchange_code(self, code: str, redirect_uri: str) -> GoogleIdentity: ...


class TokenIssuerPort(Protocol):
    """簽發與驗證本系統自己的存取權杖。"""

    def issue(self, user_id: UUID) -> str: ...

    def verify(self, token: str) -> UUID:
        """驗證失敗（過期、簽章錯、格式錯）一律 raise `Unauthorized`。"""
        ...


class ClockPort(Protocol):
    """目前時間；一律 timezone-aware UTC。"""

    def now(self) -> datetime: ...
