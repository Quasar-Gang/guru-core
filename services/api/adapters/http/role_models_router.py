"""`/role-models*` endpoints (PRD section 5): thin forwarding to the Role Model Service.

Reads and the recommendation need a JWT; the team-facing writes are protected by the
Role Model Service's own `X-API-Key`, which is passed straight through.
"""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse, Response

from services.api.adapters.http.deps import CurrentUserId, get_container
from services.api.application.recommend_role_models import RecommendationView

__all__ = ["router"]

router = APIRouter(prefix="/role-models", tags=["role-models"])

ApiKey = Annotated[str | None, Header(alias="X-API-Key")]


def _response(status: int, body: Any) -> Response:
    if body is None:
        return Response(status_code=status)
    return JSONResponse(status_code=status, content=body)


@router.get("")
async def list_role_models(
    request: Request,
    user_id: CurrentUserId,
    kind: str | None = None,
    tags: Annotated[list[str], Query()] = [],  # noqa: B006 - FastAPI query default
    match: Literal["any", "all"] = "any",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Response:
    params: dict[str, Any] = {"tags": tags, "match": match, "limit": limit}
    if kind is not None:
        params["kind"] = kind
    status, body = await get_container(request).role_model_client.forward(
        "GET", "/role-models", params=params
    )
    return _response(status, body)


@router.get("/tags")
async def list_tags(request: Request, user_id: CurrentUserId) -> Response:
    status, body = await get_container(request).role_model_client.forward(
        "GET", "/role-models/tags"
    )
    return _response(status, body)


@router.get("/recommend", response_model=list[RecommendationView])
async def recommend_role_models(
    request: Request,
    user_id: CurrentUserId,
    goal: str = "",
    domains: Annotated[list[str], Query()] = [],  # noqa: B006 - FastAPI query default
    excluded_constraints: Annotated[list[str], Query()] = [],  # noqa: B006 - same
) -> list[RecommendationView]:
    return await get_container(request).recommend_role_models(
        user_id, goal, list(domains), list(excluded_constraints)
    )


@router.get("/{role_model_id}")
async def get_role_model(request: Request, user_id: CurrentUserId, role_model_id: UUID) -> Response:
    status, body = await get_container(request).role_model_client.forward(
        "GET", f"/role-models/{role_model_id}"
    )
    return _response(status, body)


@router.post("")
async def create_role_model(
    request: Request, body: dict[str, Any], x_api_key: ApiKey = None
) -> Response:
    status, payload = await get_container(request).role_model_client.forward(
        "POST", "/role-models", json=body, api_key=x_api_key
    )
    return _response(status, payload)


@router.put("/{role_model_id}")
async def update_role_model(
    request: Request, role_model_id: UUID, body: dict[str, Any], x_api_key: ApiKey = None
) -> Response:
    status, payload = await get_container(request).role_model_client.forward(
        "PUT", f"/role-models/{role_model_id}", json=body, api_key=x_api_key
    )
    return _response(status, payload)


@router.delete("/{role_model_id}")
async def delete_role_model(
    request: Request, role_model_id: UUID, x_api_key: ApiKey = None
) -> Response:
    status, payload = await get_container(request).role_model_client.forward(
        "DELETE", f"/role-models/{role_model_id}", api_key=x_api_key
    )
    return _response(status, payload)
