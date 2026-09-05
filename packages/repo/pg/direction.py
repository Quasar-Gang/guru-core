"""PostgreSQL repos for Station 1: runs, reports, verdicts, answers, quota, hypotheses."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.repo import models
from packages.repo.entities import (
    DirectionHypothesis,
    DirectionRun,
    FitVerdict,
    NewFitVerdict,
    NewReport,
    QuestionAnswer,
    Quota,
    Report,
)

__all__ = [
    "PgDirectionHypothesisRepo",
    "PgDirectionRunRepo",
    "PgFitVerdictRepo",
    "PgQuestionAnswerRepo",
    "PgQuotaRepo",
    "PgReportRepo",
]


def _run(row: models.DirectionRun) -> DirectionRun:
    return DirectionRun(
        id=row.id,
        user_id=row.user_id,
        status=row.status,
        period_start=row.period_start,
        period_end=row.period_end,
        readouts=row.readouts,
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _report(row: models.Report) -> Report:
    return Report(
        id=row.id,
        user_id=row.user_id,
        run_id=row.run_id,
        dimension=row.dimension,
        period_start=row.period_start,
        period_end=row.period_end,
        metrics=row.metrics,
        findings=row.findings,
        created_at=row.created_at,
    )


def _verdict(row: models.FitVerdict) -> FitVerdict:
    return FitVerdict(
        id=row.id,
        user_id=row.user_id,
        run_id=row.run_id,
        role_model_id=row.role_model_id,
        fit=row.fit,
        verdict=row.verdict,
        note=row.note,
        evidence=row.evidence,
        probe=row.probe,
        created_at=row.created_at,
    )


def _answer(row: models.QuestionAnswer) -> QuestionAnswer:
    return QuestionAnswer(
        id=row.id,
        user_id=row.user_id,
        question_key=row.question_key,
        answer=row.answer,
        skipped=row.skipped,
        answered_at=row.answered_at,
    )


def _quota(row: models.Quota) -> Quota:
    return Quota(
        user_id=row.user_id,
        drop_first=row.drop_first,
        weekly_minutes=row.weekly_minutes,
        effective_from=row.effective_from,
        updated_at=row.updated_at,
    )


def _hypothesis(row: models.DirectionHypothesis) -> DirectionHypothesis:
    return DirectionHypothesis(
        id=row.id,
        user_id=row.user_id,
        version=row.version,
        role_model_id=row.role_model_id,
        fit_verdict_id=row.fit_verdict_id,
        source=row.source,
        evidence_snapshot=row.evidence_snapshot,
        drop_first=row.drop_first,
        answers_count=row.answers_count,
        review_date=row.review_date,
        created_at=row.created_at,
    )


class _Repo:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory


class PgDirectionRunRepo(_Repo):
    async def create(self, user_id: UUID) -> DirectionRun:
        async with self._session_factory() as session:
            row = models.DirectionRun(user_id=user_id)
            session.add(row)
            await session.flush()
            await session.refresh(row)
            entity = _run(row)
            await session.commit()
            return entity

    async def get(self, user_id: UUID, run_id: UUID) -> DirectionRun | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(models.DirectionRun).where(
                    models.DirectionRun.id == run_id, models.DirectionRun.user_id == user_id
                )
            )
            return _run(row) if row is not None else None

    async def get_unscoped(self, run_id: UUID) -> DirectionRun | None:
        async with self._session_factory() as session:
            row = await session.get(models.DirectionRun, run_id)
            return _run(row) if row is not None else None

    async def latest(self, user_id: UUID) -> DirectionRun | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(models.DirectionRun)
                .where(models.DirectionRun.user_id == user_id)
                .order_by(models.DirectionRun.created_at.desc())
                .limit(1)
            )
            return _run(row) if row is not None else None

    async def set_status(self, run_id: UUID, status: str, error: str | None = None) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(models.DirectionRun)
                .where(models.DirectionRun.id == run_id)
                .values(status=status, error=error)
            )
            await session.commit()

    async def set_period(self, run_id: UUID, period_start: date, period_end: date) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(models.DirectionRun)
                .where(models.DirectionRun.id == run_id)
                .values(period_start=period_start, period_end=period_end)
            )
            await session.commit()

    async def set_readouts(self, run_id: UUID, readouts: dict[str, Any]) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(models.DirectionRun)
                .where(models.DirectionRun.id == run_id)
                .values(readouts=readouts)
            )
            await session.commit()


class PgReportRepo(_Repo):
    async def replace_for_run(
        self, user_id: UUID, run_id: UUID, reports: Sequence[NewReport]
    ) -> list[Report]:
        async with self._session_factory() as session:
            await session.execute(delete(models.Report).where(models.Report.run_id == run_id))
            rows = [
                models.Report(user_id=user_id, run_id=run_id, **report.model_dump())
                for report in reports
            ]
            session.add_all(rows)
            await session.flush()
            entities = [_report(row) for row in rows]
            await session.commit()
            return entities

    async def list_for_run(self, run_id: UUID) -> list[Report]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(models.Report)
                .where(models.Report.run_id == run_id)
                .order_by(models.Report.dimension)
            )
            return [_report(row) for row in rows]


class PgFitVerdictRepo(_Repo):
    async def replace_for_run(
        self, user_id: UUID, run_id: UUID, verdicts: Sequence[NewFitVerdict]
    ) -> list[FitVerdict]:
        async with self._session_factory() as session:
            await session.execute(
                delete(models.FitVerdict).where(models.FitVerdict.run_id == run_id)
            )
            rows = [
                models.FitVerdict(user_id=user_id, run_id=run_id, **verdict.model_dump())
                for verdict in verdicts
            ]
            session.add_all(rows)
            await session.flush()
            entities = [_verdict(row) for row in rows]
            await session.commit()
            return entities

    async def list_for_run(self, run_id: UUID) -> list[FitVerdict]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(models.FitVerdict)
                .where(models.FitVerdict.run_id == run_id)
                .order_by(models.FitVerdict.created_at, models.FitVerdict.id)
            )
            return [_verdict(row) for row in rows]

    async def get(self, user_id: UUID, verdict_id: UUID) -> FitVerdict | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(models.FitVerdict).where(
                    models.FitVerdict.id == verdict_id, models.FitVerdict.user_id == user_id
                )
            )
            return _verdict(row) if row is not None else None


class PgQuestionAnswerRepo(_Repo):
    async def upsert(
        self, user_id: UUID, question_key: str, answer: str, skipped: bool, answered_at: datetime
    ) -> QuestionAnswer:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(models.QuestionAnswer).where(
                    models.QuestionAnswer.user_id == user_id,
                    models.QuestionAnswer.question_key == question_key,
                )
            )
            if row is None:
                row = models.QuestionAnswer(user_id=user_id, question_key=question_key)
                session.add(row)
            row.answer = answer
            row.skipped = skipped
            row.answered_at = answered_at
            await session.flush()
            await session.refresh(row)
            entity = _answer(row)
            await session.commit()
            return entity

    async def list_for_user(self, user_id: UUID) -> list[QuestionAnswer]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(models.QuestionAnswer)
                .where(models.QuestionAnswer.user_id == user_id)
                .order_by(models.QuestionAnswer.question_key)
            )
            return [_answer(row) for row in rows]


class PgQuotaRepo(_Repo):
    async def get(self, user_id: UUID) -> Quota | None:
        async with self._session_factory() as session:
            row = await session.get(models.Quota, user_id)
            return _quota(row) if row is not None else None

    async def upsert(
        self, user_id: UUID, drop_first: str, weekly_minutes: int, effective_from: date
    ) -> Quota:
        async with self._session_factory() as session:
            row = await session.get(models.Quota, user_id)
            if row is None:
                row = models.Quota(user_id=user_id)
                session.add(row)
            row.drop_first = drop_first
            row.weekly_minutes = weekly_minutes
            row.effective_from = effective_from
            await session.flush()
            await session.refresh(row)
            entity = _quota(row)
            await session.commit()
            return entity


class PgDirectionHypothesisRepo(_Repo):
    """Append-only. The next version is allocated inside the write transaction, so two
    concurrent appends collide on `uq_hypothesis_user_version` rather than silently
    producing two `v1`s.
    """

    async def append(
        self,
        user_id: UUID,
        role_model_id: UUID,
        fit_verdict_id: UUID,
        source: str,
        evidence_snapshot: dict[str, Any],
        drop_first: str | None,
        answers_count: int,
        review_date: date,
    ) -> DirectionHypothesis:
        async with self._session_factory() as session:
            highest = await session.scalar(
                select(func.max(models.DirectionHypothesis.version)).where(
                    models.DirectionHypothesis.user_id == user_id
                )
            )
            row = models.DirectionHypothesis(
                user_id=user_id,
                version=0 if highest is None else highest + 1,
                role_model_id=role_model_id,
                fit_verdict_id=fit_verdict_id,
                source=source,
                evidence_snapshot=evidence_snapshot,
                drop_first=drop_first,
                answers_count=answers_count,
                review_date=review_date,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            entity = _hypothesis(row)
            await session.commit()
            return entity

    async def get(self, user_id: UUID, hypothesis_id: UUID) -> DirectionHypothesis | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(models.DirectionHypothesis).where(
                    models.DirectionHypothesis.id == hypothesis_id,
                    models.DirectionHypothesis.user_id == user_id,
                )
            )
            return _hypothesis(row) if row is not None else None

    async def get_unscoped(self, hypothesis_id: UUID) -> DirectionHypothesis | None:
        async with self._session_factory() as session:
            row = await session.get(models.DirectionHypothesis, hypothesis_id)
            return _hypothesis(row) if row is not None else None

    async def list_for_user(self, user_id: UUID) -> list[DirectionHypothesis]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(models.DirectionHypothesis)
                .where(models.DirectionHypothesis.user_id == user_id)
                .order_by(models.DirectionHypothesis.version)
            )
            return [_hypothesis(row) for row in rows]

    async def latest(self, user_id: UUID) -> DirectionHypothesis | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(models.DirectionHypothesis)
                .where(models.DirectionHypothesis.user_id == user_id)
                .order_by(models.DirectionHypothesis.version.desc())
                .limit(1)
            )
            return _hypothesis(row) if row is not None else None
