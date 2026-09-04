"""停用（軟刪除）一筆 role model。"""

from uuid import UUID

from packages.repo import RoleModelRepo
from services.role_model.application.errors import NotFound


class DeactivateRoleModel:
    def __init__(self, role_models: RoleModelRepo) -> None:
        self._role_models = role_models

    async def __call__(self, role_model_id: UUID) -> None:
        if await self._role_models.get(role_model_id) is None:
            raise NotFound(f"role model {role_model_id} not found")
        await self._role_models.deactivate(role_model_id)
