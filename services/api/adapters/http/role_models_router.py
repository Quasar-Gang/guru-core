"""`/role-models*` endpoints (PRD section 5): thin forwarding to the Role Model Service.

Reads and the recommendation need a JWT; the team-facing writes are protected by the
Role Model Service's own `X-API-Key`, which is passed straight through.
"""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse, Response

from services.api.adapters.http.deps import CurrentUserId, get_container
from services.api.adapters.http.schemas import ErrorResponse
from services.api.application.recommend_role_models import RecommendationView

__all__ = ["router"]

router = APIRouter(prefix="/role-models", tags=["role-models"])

ApiKey = Annotated[str | None, Header(alias="X-API-Key")]

_UNAUTHORIZED = (
    "`unauthorized` — the `Authorization: Bearer <jwt>` header is missing or malformed, or the "
    "token has expired."
)
_RATE_LIMITED = (
    "`rate_limited` — too many requests from this caller in the last minute. The response "
    "carries `Retry-After`."
)
_BAD_API_KEY = (
    "`unauthorized` — the `X-API-Key` header is missing or does not match the Role Model "
    "Service's key. This is a team credential, not the user's JWT: a signed-in end user cannot "
    "reach this endpoint."
)
_UPSTREAM_NOT_FOUND = "`not_found` — no active role model with this id."


def _errors(*entries: tuple[int, str]) -> dict[int | str, dict[str, Any]]:
    """Document one status per entry; every one of them uses the `{"error": ...}` envelope."""
    return {code: {"model": ErrorResponse, "description": text} for code, text in entries}


def _response(status: int, body: Any) -> Response:
    if body is None:
        return Response(status_code=status)
    return JSONResponse(status_code=status, content=body)


@router.get(
    "",
    summary="Browse the role model catalogue",
    response_description=(
        "A JSON array of role model summaries (`id`, `kind`, `name`, `tags`), proxied verbatim "
        "from the Role Model Service."
    ),
    responses=_errors(
        (401, _UNAUTHORIZED),
        (422, "`invalid_input` — `limit` is outside 1–200, or `match` is not `any` / `all`."),
        (429, _RATE_LIMITED),
    ),
)
async def list_role_models(
    request: Request,
    user_id: CurrentUserId,
    kind: str | None = None,
    tags: Annotated[list[str], Query()] = [],  # noqa: B006 - FastAPI query default
    match: Literal["any", "all"] = "any",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Response:
    """The picker behind `trait_role_model_id` / `persona_role_model_id` on a plan session.

    Role models are the shared, team-curated library the plan generator borrows from: a *trait*
    model shapes how a plan is structured, a *persona* model shapes how it speaks. Filter with
    `kind`, and with `tags` repeated once per tag (`?tags=fitness&tags=beginner`) — `match=any`
    returns anything carrying one of them, `match=all` only what carries every one.

    **Auth: the user's JWT.** Reading the catalogue is open to any signed-in user; only the
    `POST` / `PUT` / `DELETE` routes below are team-only.

    Proxied straight from the Role Model Service, so the body and status are that service's,
    not this one's. The error envelope is identical in both.
    """
    params: dict[str, Any] = {"tags": tags, "match": match, "limit": limit}
    if kind is not None:
        params["kind"] = kind
    status, body = await get_container(request).role_model_client.forward(
        "GET", "/role-models", params=params
    )
    return _response(status, body)


@router.get(
    "/tags",
    summary="List the tags available for filtering",
    response_description=(
        "An object keyed by role model `kind`, each holding the tags in use for that kind."
    ),
    responses=_errors((401, _UNAUTHORIZED), (429, _RATE_LIMITED)),
)
async def list_tags(request: Request, user_id: CurrentUserId) -> Response:
    """The vocabulary for the `tags` filter of `GET /v1/role-models`.

    Use it to build the filter UI instead of hard-coding tag names: the catalogue is curated by
    the team and its tags change without an app release. Requires the user's JWT.
    """
    status, body = await get_container(request).role_model_client.forward(
        "GET", "/role-models/tags"
    )
    return _response(status, body)


@router.get(
    "/recommend",
    response_model=list[RecommendationView],
    summary="Recommend persona role models for the caller's goal",
    response_description=(
        "Up to a handful of recommendations, best first: `role_model_id`, `name`, and a `reason` "
        "written for display next to the suggestion."
    ),
    responses=_errors(
        (401, _UNAUTHORIZED),
        (
            404,
            "`not_found` — the Role Model Service could not resolve part of the request. Treat "
            "it as 'no recommendations' rather than a broken screen.",
        ),
        (
            422,
            "`invalid_input` — the Role Model Service rejected the assembled payload (for "
            "example an unusable `domains` or `excluded_constraints` value).",
        ),
        (429, _RATE_LIMITED),
        (
            500,
            "`domain_error` — the Role Model Service is unreachable or answered with an "
            "unexpected status. The screen can fall back to `GET /v1/role-models`.",
        ),
    ),
)
async def recommend_role_models(
    request: Request,
    user_id: CurrentUserId,
    goal: str = "",
    domains: Annotated[list[str], Query()] = [],  # noqa: B006 - FastAPI query default
    excluded_constraints: Annotated[list[str], Query()] = [],  # noqa: B006 - same
) -> list[RecommendationView]:
    """Suggest role models to preselect before `POST /v1/plan-sessions`.

    Pass the goal the user just typed; the API service adds their stored questionnaire answers
    (from `GET /v1/profile`) and asks the Role Model Service to rank the catalogue. `domains` and
    `excluded_constraints` are repeatable query parameters that narrow or veto candidates.

    Nothing is persisted: the result is a suggestion the user may take or ignore. Feed a chosen
    `role_model_id` into `persona_role_model_id` (or `trait_role_model_id`) when creating the
    session. Requires the user's JWT — the recommendation is personalised to the caller.
    """
    return await get_container(request).recommend_role_models(
        user_id, goal, list(domains), list(excluded_constraints)
    )


@router.get(
    "/{role_model_id}",
    summary="Read one role model in full",
    response_description=(
        "The full record — `id`, `kind`, `name`, `tags` and the `content` document — proxied "
        "from the Role Model Service."
    ),
    responses=_errors(
        (401, _UNAUTHORIZED),
        (404, _UPSTREAM_NOT_FOUND),
        (429, _RATE_LIMITED),
    ),
)
async def get_role_model(request: Request, user_id: CurrentUserId, role_model_id: UUID) -> Response:
    """The detail view behind a catalogue entry, for the screen where a user picks one.

    `content` is the curated document the plan generator reads; its shape belongs to the Role
    Model Service and is not part of this API's contract, so render it defensively. Requires the
    user's JWT.
    """
    status, body = await get_container(request).role_model_client.forward(
        "GET", f"/role-models/{role_model_id}"
    )
    return _response(status, body)


@router.post(
    "",
    summary="Create a role model (team only, X-API-Key)",
    response_description=(
        "The created record. The upstream status is passed through unchanged, so a successful "
        "create actually arrives as `201` even though the schema declares `200`."
    ),
    responses=_errors(
        (401, _BAD_API_KEY),
        (422, "`invalid_input` — the body is missing `kind` or `name`, or `name` is empty."),
        (429, _RATE_LIMITED),
    ),
)
async def create_role_model(
    request: Request, body: dict[str, Any], x_api_key: ApiKey = None
) -> Response:
    """Add an entry to the shared catalogue. **Content tooling only — not an app endpoint.**

    **Auth: `X-API-Key`, not a JWT.** The header is forwarded to the Role Model Service, which
    checks it; no user token is involved and no user context is recorded. The catalogue is global,
    so anything created here is visible to every signed-in user.

    The body is passed through unvalidated by this service: `kind` and a non-empty `name` are
    required, with optional `tags` (list of strings) and `content` (a free-form object whose shape
    the Role Model Service defines). The status and body of the response are the upstream ones.
    """
    status, payload = await get_container(request).role_model_client.forward(
        "POST", "/role-models", json=body, api_key=x_api_key
    )
    return _response(status, payload)


@router.put(
    "/{role_model_id}",
    summary="Replace a role model (team only, X-API-Key)",
    response_description="The updated record, proxied from the Role Model Service.",
    responses=_errors(
        (401, _BAD_API_KEY),
        (404, _UPSTREAM_NOT_FOUND),
        (422, "`invalid_input` — the body is missing `kind` or `name`, or `name` is empty."),
        (429, _RATE_LIMITED),
    ),
)
async def update_role_model(
    request: Request, role_model_id: UUID, body: dict[str, Any], x_api_key: ApiKey = None
) -> Response:
    """Overwrite one catalogue entry. **Content tooling only — not an app endpoint.**

    **Auth: `X-API-Key`, not a JWT.** A full replacement, not a patch: fields left out of the body
    are cleared, so send the whole record. Plans already generated from this role model keep the
    text they were generated with — the edit only affects future generation.
    """
    status, payload = await get_container(request).role_model_client.forward(
        "PUT", f"/role-models/{role_model_id}", json=body, api_key=x_api_key
    )
    return _response(status, payload)


@router.delete(
    "/{role_model_id}",
    summary="Retire a role model (team only, X-API-Key)",
    response_description=(
        "An empty body. The upstream status is passed through unchanged, so this actually "
        "arrives as `204` even though the schema declares `200`."
    ),
    responses=_errors(
        (401, _BAD_API_KEY),
        (404, _UPSTREAM_NOT_FOUND),
        (429, _RATE_LIMITED),
    ),
)
async def delete_role_model(
    request: Request, role_model_id: UUID, x_api_key: ApiKey = None
) -> Response:
    """Take an entry out of the catalogue. **Content tooling only — not an app endpoint.**

    **Auth: `X-API-Key`, not a JWT.** Upstream this deactivates rather than erases: the role model
    stops appearing in `GET /v1/role-models`, while plans and sessions that referenced it stay
    intact. The response carries no body.
    """
    status, payload = await get_container(request).role_model_client.forward(
        "DELETE", f"/role-models/{role_model_id}", api_key=x_api_key
    )
    return _response(status, payload)
