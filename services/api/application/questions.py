"""The three constraint questions, and the Quota that Q-3 sets.

Every question is skippable, and skipping is a first-class answer rather than an omission:
the Direction Hypothesis records how many of the three were answered, so a hypothesis built
on one answer is visibly different from one built on three.

Answering Q-3 writes the Quota. That is the only place a user tells the system what it may
spend, so it happens here, once, rather than being inferred anywhere else.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from packages.queue import ProfileBuildJobV1, QueuePort
from packages.repo import QuestionAnswerRepo, QuotaRepo
from packages.repo.entities import QuestionAnswer
from services.api.application.ports import ClockPort
from services.api.domain.errors import NotFound
from services.api.domain.questions import QUESTIONS, parse_area, question

__all__ = ["AnswerQuestion", "AnswerView", "GetQuota", "ListQuestions", "QuestionView", "QuotaView"]

#: What the schedule may spend a week when Q-3 is answered. Modest on purpose: a quota that
#: fits is a quota that survives contact with a real week.
DEFAULT_WEEKLY_MINUTES = 300

_Q3 = "q3"


class QuestionView(BaseModel):
    """One question, its stated purpose, and whatever the user has said so far."""

    key: str
    prompt: str
    purpose: str
    choices: list[str]
    answer: str | None = None
    skipped: bool = False
    answered_at: datetime | None = None


class AnswerView(BaseModel):
    key: str
    answer: str
    skipped: bool
    answered_at: datetime


class QuotaView(BaseModel):
    """What Q-3 declared: the weekly ceiling, and what gets cut first."""

    drop_first: str
    weekly_minutes: int
    effective_from: datetime | None = None


class ListQuestions:
    """All three, always — a skipped question stays visible and answerable later."""

    def __init__(self, answers: QuestionAnswerRepo) -> None:
        self._answers = answers

    async def __call__(self, user_id: UUID) -> list[QuestionView]:
        stored = {row.question_key: row for row in await self._answers.list_for_user(user_id)}
        return [
            QuestionView(
                key=item.key,
                prompt=item.prompt,
                purpose=item.purpose,
                choices=list(item.choices),
                **_answered(stored.get(item.key)),
            )
            for item in QUESTIONS
        ]


class AnswerQuestion:
    """Record an answer — or a skip — and let it back into the pipeline.

    An answer is personal data, so it returns to the Uploader rather than going forward:
    it changes the Profile, the Reports, and every verdict downstream. Disagreement is an
    input to the pipeline, not an exception path around it.
    """

    def __init__(
        self,
        answers: QuestionAnswerRepo,
        quotas: QuotaRepo,
        queue: QueuePort,
        clock: ClockPort,
    ) -> None:
        self._answers = answers
        self._quotas = quotas
        self._queue = queue
        self._clock = clock

    async def __call__(self, user_id: UUID, key: str, answer: str, skipped: bool) -> AnswerView:
        spec = question(key)
        text = "" if skipped else answer.strip()
        if spec.key == _Q3 and not skipped:
            area = parse_area(text)
            await self._quotas.upsert(
                user_id, area, DEFAULT_WEEKLY_MINUTES, self._clock.now().date()
            )
            text = area

        now = self._clock.now()
        stored = await self._answers.upsert(user_id, spec.key, text, skipped, now)
        if not skipped:
            await self._queue.enqueue(ProfileBuildJobV1(user_id=user_id))
        return AnswerView(
            key=stored.question_key,
            answer=stored.answer,
            skipped=stored.skipped,
            answered_at=stored.answered_at,
        )


class GetQuota:
    def __init__(self, quotas: QuotaRepo) -> None:
        self._quotas = quotas

    async def __call__(self, user_id: UUID) -> QuotaView:
        found = await self._quotas.get(user_id)
        if found is None:
            raise NotFound("no quota yet; answer q3 to set one")
        return QuotaView(
            drop_first=found.drop_first,
            weekly_minutes=found.weekly_minutes,
            effective_from=datetime.combine(found.effective_from, datetime.min.time()),
        )


def _answered(row: QuestionAnswer | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {"answer": row.answer, "skipped": row.skipped, "answered_at": row.answered_at}
