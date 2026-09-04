"""Role Model Service 的應用層錯誤。

刻意不與其他 service 共用：service 之間不得互相 import，因此每個 service
自己定義同名概念，由 adapter 對應成 HTTP 狀態碼。
"""


class RoleModelError(Exception):
    """Role Model Service 應用層錯誤的基底。"""


class NotFound(RoleModelError):
    """指定的 role model 不存在。"""


class InvalidInput(RoleModelError):
    """tag 或 content 不合法（PRD 12.3 / 12.4）。"""


class Unauthorized(RoleModelError):
    """缺少或錯誤的 X-API-Key。"""
