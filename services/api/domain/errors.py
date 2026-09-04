"""API Service domain 的錯誤型別。

純 Python，不知道 HTTP。HTTP status 的對應在
`services/api/adapters/http/app.py`（`STATUS_BY_ERROR`）。
"""

__all__ = [
    "Conflict",
    "DomainError",
    "Forbidden",
    "InvalidInput",
    "NotFound",
    "ReauthRequired",
    "Unauthorized",
]


class DomainError(Exception):
    """所有 API domain 錯誤的基底。"""


class NotFound(DomainError):
    """要找的資源不存在，或不屬於這個使用者。"""


class Forbidden(DomainError):
    """使用者已驗證，但不允許做這件事。"""


class Conflict(DomainError):
    """與目前狀態衝突（重複建立、狀態機不允許）。"""


class InvalidInput(DomainError):
    """輸入不合法。"""


class Unauthorized(DomainError):
    """缺少或無效的憑證。"""


class ReauthRequired(DomainError):
    """第三方授權失效，使用者必須重新連線。"""
