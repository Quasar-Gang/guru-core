"""The Role Model catalogue as the app reads it, plus writing your own."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from packages.repo.entities import NewRoleModel
from services.api.adapters.http.deps import CurrentUserId, get_container
from services.api.adapters.http.schemas import ErrorResponse
from services.api.application.catalog import RoleModelView

__all__ = ["AuthorRoleModelRequest", "router"]

router = APIRouter(tags=["role-models"])

_UNAUTHORIZED = {
    "model": ErrorResponse,
    "description": "`unauthorized` — missing, invalid or expired bearer token.",
}


class AuthorRoleModelRequest(BaseModel):
    """Your own shape. Every field is required — `cost` included, and especially."""

    code: str = Field(min_length=1, max_length=16, examples=["MY-1"])
    name: str = Field(min_length=1, max_length=128)
    vision: str = Field(min_length=1)
    five_year_path: str = Field(min_length=1)
    must_accumulate: str = Field(min_length=1)
    cost: str = Field(
        min_length=1,
        description=(
            "What this shape costs you. Required: a template with no stated trade-off is a "
            "popularity contest entry, won by whichever sounds best out loud."
        ),
    )
    tags: list[str] = Field(default_factory=list, examples=[["shape:depth", "area:career"]])


@router.get(
    "/role-models",
    response_model=list[RoleModelView],
    summary="The six shipped shapes, plus your own",
    responses={401: _UNAUTHORIZED},
)
async def list_role_models(request: Request, user_id: CurrentUserId) -> list[RoleModelView]:
    """These are not occupations. They are shapes a life can take.

    The same job title can grow into different shapes, and different job titles can be the
    same shape. Every one states its cost, and picking one is not a commitment — it only
    gives the next step something to compare against.
    """
    return await get_container(request).list_role_models(user_id)


@router.post(
    "/role-models",
    response_model=RoleModelView,
    status_code=201,
    summary="Write your own shape",
    responses={
        401: _UNAUTHORIZED,
        422: {
            "model": ErrorResponse,
            "description": "`invalid_input` — a field is missing, `cost` included.",
        },
    },
)
async def author_role_model(
    request: Request, user_id: CurrentUserId, body: AuthorRoleModelRequest
) -> RoleModelView:
    """A user-authored template is a Role Model like any other.

    It is scored alongside the shipped six, on the same terms, with the same rule that it
    must state what it costs. It is visible only to you.
    """
    return await get_container(request).author_role_model(
        user_id, NewRoleModel.model_validate(body.model_dump())
    )
