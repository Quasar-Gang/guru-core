"""The three constraint questions, and the quota Q-3 sets."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from services.api.adapters.http.deps import CurrentUserId, get_container
from services.api.adapters.http.schemas import ErrorResponse
from services.api.application.questions import AnswerView, QuestionView, QuotaView

__all__ = ["AnswerRequest", "router"]

router = APIRouter(tags=["questions"])

_UNAUTHORIZED = {
    "model": ErrorResponse,
    "description": "`unauthorized` — missing, invalid or expired bearer token.",
}


class AnswerRequest(BaseModel):
    """Answer, or skip. Skipping is a real answer and is recorded as one."""

    answer: str = ""
    skipped: bool = False


@router.get(
    "/questions",
    response_model=list[QuestionView],
    summary="The three questions, each with the reason it is being asked",
    response_description="All three, always, with whatever has been answered so far.",
    responses={401: _UNAUTHORIZED},
)
async def list_questions(request: Request, user_id: CurrentUserId) -> list[QuestionView]:
    """Three questions that need no direction to answer, and no question before them.

    "What do you want" is hard for someone without direction. These are not: Q-1 asks what
    you are certain you *do not* want, because ruling paths out is cheaper than picking one.
    Q-2 asks about the pattern of giving things up, which is the baseline Station 3 needs to
    tell a growth-driven revision from an avoidance-driven one. Q-3 forces a ranking, and
    the answer becomes the quota.

    Every one is skippable, and a skipped question stays visible and answerable later.
    """
    return await get_container(request).list_questions(user_id)


@router.put(
    "/questions/{key}",
    response_model=AnswerView,
    summary="Answer one question, or skip it",
    responses={
        401: _UNAUTHORIZED,
        422: {
            "model": ErrorResponse,
            "description": (
                "`invalid_input` — `key` is not q1, q2 or q3, or q3 was answered with "
                "something other than `career`, `relationships` or `health`."
            ),
        },
    },
)
async def answer_question(
    request: Request, user_id: CurrentUserId, key: str, body: AnswerRequest
) -> AnswerView:
    """An answer is personal data, so it goes back to the Uploader rather than forward.

    It changes the Profile, the Reports, and every verdict downstream — disagreement is an
    input to the pipeline, not an exception path around it. Answering re-queues the Profile
    build; run the direction pass again afterwards to see the verdicts move.

    Answering q3 also writes the quota: a weekly ceiling, and what gets cut first when
    capacity runs short.
    """
    return await get_container(request).answer_question(user_id, key, body.answer, body.skipped)


@router.get(
    "/quota",
    response_model=QuotaView,
    summary="What the schedule may spend, and what it drops first",
    responses={
        401: _UNAUTHORIZED,
        404: {"model": ErrorResponse, "description": "`not_found` — q3 has not been answered."},
    },
)
async def get_quota(request: Request, user_id: CurrentUserId) -> QuotaView:
    """Declared, not observed.

    Capacity is what is physically possible and comes off the calendar. The quota is what
    has been allowed, and it comes from q3. The Schedule satisfies both, and when they
    disagree the quota's cut order decides.
    """
    return await get_container(request).get_quota(user_id)
