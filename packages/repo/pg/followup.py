"""PgFollowupRoundRepo — PostgreSQL implementation of the followup_rounds table."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.repo import models
from packages.repo.entities import FollowupRound


def _to_entity(row: models.FollowupRound) -> FollowupRound:
    return FollowupRound(
        id=row.id,
        session_id=row.session_id,
        round_no=row.round_no,
        questions=list(row.questions),
        answers=list(row.answers) if row.answers is not None else None,
        answered_at=row.answered_at,
        created_at=row.created_at,
    )


class PgFollowupRoundRepo:
    """PostgreSQL FollowupRoundRepo."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self, session_id: UUID, round_no: int, questions: list[dict[str, Any]]
    ) -> FollowupRound:
        async with self._session_factory() as session:
            row = models.FollowupRound(
                session_id=session_id, round_no=round_no, questions=list(questions)
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            entity = _to_entity(row)
            await session.commit()
            return entity

    async def latest(self, session_id: UUID) -> FollowupRound | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(models.FollowupRound)
                .where(models.FollowupRound.session_id == session_id)
                .order_by(models.FollowupRound.round_no.desc())
                .limit(1)
            )
            return _to_entity(row) if row is not None else None

    async def list_for_session(self, session_id: UUID) -> list[FollowupRound]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(models.FollowupRound)
                .where(models.FollowupRound.session_id == session_id)
                .order_by(models.FollowupRound.round_no)
            )
            return [_to_entity(row) for row in rows]

    async def record_answers(
        self, round_id: UUID, answers: list[dict[str, Any]], answered_at: datetime
    ) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(models.FollowupRound)
                .where(models.FollowupRound.id == round_id)
                .values(answers=list(answers), answered_at=answered_at)
            )
            await session.commit()
