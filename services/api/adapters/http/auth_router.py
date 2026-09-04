"""Login and current-user endpoints."""

from fastapi import APIRouter, Request

from services.api.adapters.http.deps import CurrentUserId, get_container
from services.api.adapters.http.schemas import GoogleLoginRequest, LoginResponse, MeResponse
from services.api.domain.errors import NotFound

__all__ = ["router"]

router = APIRouter(tags=["auth"])


@router.post("/auth/google", response_model=LoginResponse)
async def login_with_google(request: Request, body: GoogleLoginRequest) -> LoginResponse:
    result = await get_container(request).login_with_google(body.code, body.redirect_uri)
    return LoginResponse(
        access_token=result.access_token,
        user_id=result.user_id,
        email=result.email,
        is_new_user=result.is_new_user,
    )


@router.get("/me", response_model=MeResponse)
async def me(request: Request, user_id: CurrentUserId) -> MeResponse:
    user = await get_container(request).users.get(user_id)
    if user is None:
        raise NotFound("user not found")
    return MeResponse(user_id=user.id, email=user.email)
