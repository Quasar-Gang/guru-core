"""Plan Engine domain 的錯誤型別。"""


class PlanEngineDomainError(ValueError):
    """Plan Engine domain 錯誤的基底。"""


class IllegalTransition(PlanEngineDomainError):
    """session 狀態機不允許的轉移。"""
