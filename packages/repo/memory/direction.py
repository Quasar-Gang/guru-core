"""In-memory repos for Station 1."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

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
from packages.repo.memory.identity import now

__all__ = [
    "InMemoryDirectionHypothesisRepo",
    "InMemoryDirectionRunRepo",
    "InMemoryFitVerdictRepo",
    "InMemoryQuestionAnswerRepo",
    "InMemoryQuotaRepo",
    "InMemoryReportRepo",
]


class InMemoryDirectionRunRepo:
    def __init__(self) -> None:
        self._rows: dict[UUID, DirectionRun] = {}

    async def create(self, user_id: UUID) -> DirectionRun:
        moment = now()
        row = DirectionRun(
            id=uuid4(),
            user_id=user_id,
            status="pending",
            period_start=None,
            period_end=None,
            readouts={},
            error=None,
            created_at=moment,
            updated_at=moment,
        )
        self._rows[row.id] = row
        return row

    async def get(self, user_id: UUID, run_id: UUID) -> DirectionRun | None:
        row = self._rows.get(run_id)
        return row if row is not None and row.user_id == user_id else None

    async def get_unscoped(self, run_id: UUID) -> DirectionRun | None:
        return self._rows.get(run_id)

    async def latest(self, user_id: UUID) -> DirectionRun | None:
        rows = [row for row in self._rows.values() if row.user_id == user_id]
        return max(rows, key=lambda row: row.created_at, default=None)

    async def set_status(self, run_id: UUID, status: str, error: str | None = None) -> None:
        self._update(run_id, {"status": status, "error": error})

    async def set_period(self, run_id: UUID, period_start: date, period_end: date) -> None:
        self._update(run_id, {"period_start": period_start, "period_end": period_end})

    async def set_readouts(self, run_id: UUID, readouts: dict[str, Any]) -> None:
        self._update(run_id, {"readouts": readouts})

    def _update(self, run_id: UUID, fields: dict[str, Any]) -> None:
        row = self._rows.get(run_id)
        if row is not None:
            self._rows[run_id] = row.model_copy(update={**fields, "updated_at": now()})


class InMemoryReportRepo:
    def __init__(self) -> None:
        self._rows: list[Report] = []

    async def replace_for_run(
        self, user_id: UUID, run_id: UUID, reports: Sequence[NewReport]
    ) -> list[Report]:
        self._rows = [row for row in self._rows if row.run_id != run_id]
        created = [
            Report(id=uuid4(), user_id=user_id, run_id=run_id, created_at=now(), **r.model_dump())
            for r in reports
        ]
        self._rows.extend(created)
        return created

    async def list_for_run(self, run_id: UUID) -> list[Report]:
        rows = [row for row in self._rows if row.run_id == run_id]
        return sorted(rows, key=lambda row: row.dimension)


class InMemoryFitVerdictRepo:
    def __init__(self) -> None:
        self._rows: list[FitVerdict] = []

    async def replace_for_run(
        self, user_id: UUID, run_id: UUID, verdicts: Sequence[NewFitVerdict]
    ) -> list[FitVerdict]:
        self._rows = [row for row in self._rows if row.run_id != run_id]
        created = [
            FitVerdict(
                id=uuid4(), user_id=user_id, run_id=run_id, created_at=now(), **v.model_dump()
            )
            for v in verdicts
        ]
        self._rows.extend(created)
        return created

    async def list_for_run(self, run_id: UUID) -> list[FitVerdict]:
        return [row for row in self._rows if row.run_id == run_id]

    async def get(self, user_id: UUID, verdict_id: UUID) -> FitVerdict | None:
        return next(
            (row for row in self._rows if row.id == verdict_id and row.user_id == user_id), None
        )


class InMemoryQuestionAnswerRepo:
    def __init__(self) -> None:
        self._rows: dict[tuple[UUID, str], QuestionAnswer] = {}

    async def upsert(
        self, user_id: UUID, question_key: str, answer: str, skipped: bool, answered_at: datetime
    ) -> QuestionAnswer:
        existing = self._rows.get((user_id, question_key))
        row = QuestionAnswer(
            id=existing.id if existing else uuid4(),
            user_id=user_id,
            question_key=question_key,
            answer=answer,
            skipped=skipped,
            answered_at=answered_at,
        )
        self._rows[(user_id, question_key)] = row
        return row

    async def list_for_user(self, user_id: UUID) -> list[QuestionAnswer]:
        rows = [row for key, row in self._rows.items() if key[0] == user_id]
        return sorted(rows, key=lambda row: row.question_key)


class InMemoryQuotaRepo:
    def __init__(self) -> None:
        self._rows: dict[UUID, Quota] = {}

    async def get(self, user_id: UUID) -> Quota | None:
        return self._rows.get(user_id)

    async def upsert(
        self, user_id: UUID, drop_first: str, weekly_minutes: int, effective_from: date
    ) -> Quota:
        row = Quota(
            user_id=user_id,
            drop_first=drop_first,
            weekly_minutes=weekly_minutes,
            effective_from=effective_from,
            updated_at=now(),
        )
        self._rows[user_id] = row
        return row


class InMemoryDirectionHypothesisRepo:
    """Append-only, exactly like the PostgreSQL one: there is no update method."""

    def __init__(self) -> None:
        self._rows: list[DirectionHypothesis] = []

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
        versions = [row.version for row in self._rows if row.user_id == user_id]
        row = DirectionHypothesis(
            id=uuid4(),
            user_id=user_id,
            version=max(versions) + 1 if versions else 0,
            role_model_id=role_model_id,
            fit_verdict_id=fit_verdict_id,
            source=source,
            evidence_snapshot=evidence_snapshot,
            drop_first=drop_first,
            answers_count=answers_count,
            review_date=review_date,
            created_at=now(),
        )
        self._rows.append(row)
        return row

    async def get(self, user_id: UUID, hypothesis_id: UUID) -> DirectionHypothesis | None:
        return next(
            (row for row in self._rows if row.id == hypothesis_id and row.user_id == user_id), None
        )

    async def get_unscoped(self, hypothesis_id: UUID) -> DirectionHypothesis | None:
        return next((row for row in self._rows if row.id == hypothesis_id), None)

    async def list_for_user(self, user_id: UUID) -> list[DirectionHypothesis]:
        rows = [row for row in self._rows if row.user_id == user_id]
        return sorted(rows, key=lambda row: row.version)

    async def latest(self, user_id: UUID) -> DirectionHypothesis | None:
        rows = [row for row in self._rows if row.user_id == user_id]
        return max(rows, key=lambda row: row.version, default=None)
