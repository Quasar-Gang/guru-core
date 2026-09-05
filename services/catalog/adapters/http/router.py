"""`/role-models*` — the Catalog Service's whole surface.

Reads are open: the catalogue is the same for everybody and carries no user data. Writes
are team-only and authenticate with `X-API-Key`; a user authoring their own template does
it through the API Service, which owns the notion of who is asking.
"""

from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from services.catalog.adapters.http.deps import api_key_guard
from services.catalog.adapters.http.schemas import RoleModelView, UpsertRoleModelRequest
from services.catalog.domain.template import RoleModelTemplate

if TYPE_CHECKING:  # pragma: no cover - type-only, avoids a container <-> adapters import cycle
    from services.catalog.container import CatalogContainer

__all__ = ["build_router"]


def build_router(container: "CatalogContainer") -> APIRouter:
    router = APIRouter(prefix="/role-models", tags=["role-models"])
    protected = [Depends(api_key_guard(container.settings.catalog_api_key))]

    @router.get("", response_model=list[RoleModelView])
    async def list_role_models(
        tags: Annotated[list[str], Query()] = [],  # noqa: B006 - FastAPI query default
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> list[RoleModelView]:
        """The active shipped templates, newest revision of each."""
        found = await container.list_role_models(tags_any=tags or None, limit=limit)
        return [RoleModelView.of(role_model) for role_model in found]

    @router.get("/tags", response_model=list[str])
    async def list_tags() -> list[str]:
        return await container.list_tags()

    @router.get("/{role_model_id}", response_model=RoleModelView)
    async def get_role_model(role_model_id: UUID) -> RoleModelView:
        return RoleModelView.of(await container.get_role_model(role_model_id))

    @router.put("", response_model=RoleModelView, dependencies=protected)
    async def upsert_role_model(body: UpsertRoleModelRequest) -> RoleModelView:
        """Insert by `code`, or revise the template already carrying it."""
        template = RoleModelTemplate.model_validate(body.model_dump())
        return RoleModelView.of(await container.upsert_role_model(template))

    @router.delete("/{role_model_id}", status_code=204, dependencies=protected)
    async def retire_role_model(role_model_id: UUID) -> Response:
        """Deactivate rather than delete: a Direction Hypothesis may still point here."""
        await container.deactivate_role_model(role_model_id)
        return Response(status_code=204)

    return router
