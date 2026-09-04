"""Third-party connection endpoints: authorize, callback, list, disconnect (PRD 5)."""

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from services.api.adapters.http.deps import CurrentUserId, get_container
from services.api.application.list_integrations import IntegrationView

__all__ = ["AuthorizeUrlResponse", "CallbackRequest", "router"]

router = APIRouter(tags=["integrations"])


class AuthorizeUrlResponse(BaseModel):
    authorize_url: str


class CallbackRequest(BaseModel):
    code: str


@router.get("/integrations", response_model=list[IntegrationView])
async def list_integrations(request: Request, user_id: CurrentUserId) -> list[IntegrationView]:
    return await get_container(request).list_integrations(user_id)


@router.get("/integrations/{provider}/authorize", response_model=AuthorizeUrlResponse)
async def authorize_integration(
    request: Request, user_id: CurrentUserId, provider: str
) -> AuthorizeUrlResponse:
    url = await get_container(request).authorize_integration(user_id, provider)
    return AuthorizeUrlResponse(authorize_url=url)


@router.post("/integrations/{provider}/callback", response_model=IntegrationView)
async def complete_integration(
    request: Request, user_id: CurrentUserId, provider: str, body: CallbackRequest
) -> IntegrationView:
    return await get_container(request).complete_integration(user_id, provider, body.code)


@router.delete("/integrations/{provider}", status_code=204)
async def disconnect_integration(
    request: Request, user_id: CurrentUserId, provider: str
) -> Response:
    await get_container(request).disconnect_integration(user_id, provider)
    return Response(status_code=204)
