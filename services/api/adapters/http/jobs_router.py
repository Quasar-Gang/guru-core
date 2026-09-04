"""Background job polling endpoint."""

from fastapi import APIRouter, Request

from services.api.adapters.http.deps import CurrentUserId, get_container
from services.api.application.get_job import JobView

__all__ = ["router"]

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=JobView)
async def get_job(request: Request, user_id: CurrentUserId, job_id: str) -> JobView:
    """Job records carry no user id (global constraint 11), so this only requires a login."""
    return await get_container(request).get_job(job_id)
