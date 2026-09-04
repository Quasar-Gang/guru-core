"""`/role-models*` routes (Role Model Service, port 8001)."""

from typing import TYPE_CHECKING, Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from services.role_model.adapters.http.deps import api_key_guard
from services.role_model.adapters.http.schemas import UpsertRoleModelRequest
from services.role_model.application import RoleModelSummary, RoleModelView
from services.role_model.application.recommend_role_models import (
    Recommendation,
    RecommendInput,
)

if TYPE_CHECKING:  # pragma: no cover - type-only, avoids a container <-> adapters import cycle
    from services.role_model.container import RoleModelContainer


def build_router(container: "RoleModelContainer") -> APIRouter:
    router = APIRouter(prefix="/role-models", tags=["role-models"])
    protected = [Depends(api_key_guard(container.settings.role_model_api_key))]

    @router.get("", response_model=list[RoleModelSummary])
    async def list_role_models(
        kind: str | None = None,
        tags: Annotated[list[str], Query()] = [],  # noqa: B006 - FastAPI query default
        match: Literal["any", "all"] = "any",
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> list[RoleModelSummary]:
        return await container.list_role_models(kind=kind, tags=tags, match=match, limit=limit)

    @router.get("/tags", response_model=dict[str, list[str]])
    async def list_tags() -> dict[str, list[str]]:
        return await container.list_tags()

    @router.post("/recommend", response_model=list[Recommendation])
    async def recommend_role_models(body: RecommendInput) -> list[Recommendation]:
        """POST rather than GET: the user profile is a nested object, not a query string.

        The public, JWT-protected `GET /v1/role-models/recommend` lives in the API service,
        which builds this payload from the caller's profile and forwards it here.
        """
        return await container.recommend_role_models(body)

    @router.get("/{role_model_id}", response_model=RoleModelView)
    async def get_role_model(role_model_id: UUID) -> RoleModelView:
        return await container.get_role_model(role_model_id)

    @router.post("", response_model=RoleModelView, status_code=201, dependencies=protected)
    async def create_role_model(body: UpsertRoleModelRequest) -> RoleModelView:
        return await container.upsert_role_model(
            role_model_id=None,
            kind=body.kind,
            name=body.name,
            tags=body.tags,
            content=body.content,
        )

    @router.put("/{role_model_id}", response_model=RoleModelView, dependencies=protected)
    async def update_role_model(role_model_id: UUID, body: UpsertRoleModelRequest) -> RoleModelView:
        await container.get_role_model(role_model_id)
        return await container.upsert_role_model(
            role_model_id=role_model_id,
            kind=body.kind,
            name=body.name,
            tags=body.tags,
            content=body.content,
        )

    @router.delete("/{role_model_id}", status_code=204, dependencies=protected)
    async def delete_role_model(role_model_id: UUID) -> Response:
        await container.deactivate_role_model(role_model_id)
        return Response(status_code=204)

    return router
