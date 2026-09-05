"""Station 1 over HTTP: start a run, and read what it produced.

The run itself belongs to the Engine. What lives here is starting it and reading it back —
the Reports screen, then the six Fit Verdicts, in that order, because the data is meant to
speak before any shape is proposed.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from packages.queue import DirectionRunJobV1, QueuePort
from packages.repo import (
    DirectionRunRepo,
    FitVerdictRepo,
    ProfileRepo,
    ReportRepo,
    RoleModelRepo,
)
from packages.repo.entities import FitVerdict, Report, RoleModel
from services.api.domain.errors import Conflict, NotFound

__all__ = [
    "DirectionRunView",
    "GetDirectionRun",
    "ProfileView",
    "ReadProfile",
    "ReportView",
    "StartDirectionRun",
    "VerdictView",
]

_ACTIVE = ("pending", "analyzing", "recommending")


class ProfileView(BaseModel):
    """The system's read of who the user is now. One per user, revised in place."""

    timezone: str
    signals: dict[str, Any] = Field(default_factory=dict)
    coverage: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime | None = None


class ReportView(BaseModel):
    """One dimension: the numbers, and what they mean."""

    id: UUID
    dimension: str
    period_start: date
    period_end: date
    metrics: dict[str, Any]
    findings: dict[str, Any]


class VerdictView(BaseModel):
    """One Role Model held against this user's evidence, with its probe."""

    id: UUID
    role_model_id: UUID
    role_model_code: str
    role_model_name: str
    cost: str
    fit: str
    verdict: str
    note: str
    evidence: list[dict[str, Any]]
    probe: dict[str, Any]


class DirectionRunView(BaseModel):
    """Everything the intake screens poll for, in the order they need it."""

    id: UUID
    status: str
    period_start: date | None
    period_end: date | None
    readouts: dict[str, Any]
    error: str | None
    reports: list[ReportView]
    verdicts: list[VerdictView]


class ReadProfile:
    """A user with no uploads has no Profile yet, and that is a normal answer."""

    def __init__(self, profiles: ProfileRepo) -> None:
        self._profiles = profiles

    async def __call__(self, user_id: UUID) -> ProfileView:
        found = await self._profiles.get(user_id)
        if found is None:
            return ProfileView(timezone="UTC")
        return ProfileView(
            timezone=found.timezone,
            signals=found.signals,
            coverage=found.coverage,
            updated_at=found.updated_at,
        )


class StartDirectionRun:
    """Queue one pass of analysis and recommendation.

    Only one may be in flight: a second run would write Reports the first one's verdicts
    were never scored against, and the citation rule would quietly stop meaning anything.
    """

    def __init__(self, runs: DirectionRunRepo, profiles: ProfileRepo, queue: QueuePort) -> None:
        self._runs = runs
        self._profiles = profiles
        self._queue = queue

    async def __call__(self, user_id: UUID) -> DirectionRunView:
        profile = await self._profiles.get(user_id)
        # A row exists from the moment someone signs in — it holds their timezone. What
        # matters here is whether it was built from anything.
        if profile is None or not _has_data(profile.coverage):
            raise Conflict("upload something first; there is nothing to read yet")
        latest = await self._runs.latest(user_id)
        if latest is not None and latest.status in _ACTIVE:
            raise Conflict(f"a direction run is already {latest.status}")
        created = await self._runs.create(user_id)
        await self._queue.enqueue(DirectionRunJobV1(run_id=created.id))
        return DirectionRunView(
            id=created.id,
            status=created.status,
            period_start=None,
            period_end=None,
            readouts={},
            error=None,
            reports=[],
            verdicts=[],
        )


class GetDirectionRun:
    """One run with whatever it has produced so far; `None` means the latest one."""

    def __init__(
        self,
        runs: DirectionRunRepo,
        reports: ReportRepo,
        verdicts: FitVerdictRepo,
        role_models: RoleModelRepo,
    ) -> None:
        self._runs = runs
        self._reports = reports
        self._verdicts = verdicts
        self._role_models = role_models

    async def __call__(self, user_id: UUID, run_id: UUID | None = None) -> DirectionRunView:
        run = (
            await self._runs.get(user_id, run_id)
            if run_id is not None
            else await self._runs.latest(user_id)
        )
        if run is None:
            raise NotFound("no direction run yet")
        reports = await self._reports.list_for_run(run.id)
        verdicts = await self._verdicts.list_for_run(run.id)
        catalogue = {
            model.id: model for model in await self._role_models.list(author_user_id=user_id)
        }
        return DirectionRunView(
            id=run.id,
            status=run.status,
            period_start=run.period_start,
            period_end=run.period_end,
            readouts=run.readouts,
            error=run.error,
            reports=[_report_view(row) for row in reports],
            verdicts=[
                _verdict_view(row, catalogue.get(row.role_model_id))
                for row in sorted(verdicts, key=lambda row: _code(catalogue, row))
            ],
        )


def _has_data(coverage: dict[str, Any]) -> bool:
    return bool(coverage.get("events") or coverage.get("text_chunks"))


def _code(catalogue: dict[UUID, RoleModel], verdict: FitVerdict) -> str:
    """Order the verdicts by the catalogue's own codes, so S-1 always comes before S-2."""
    model = catalogue.get(verdict.role_model_id)
    return model.code if model is not None else ""


def _report_view(row: Report) -> ReportView:
    return ReportView(
        id=row.id,
        dimension=row.dimension,
        period_start=row.period_start,
        period_end=row.period_end,
        metrics=row.metrics,
        findings=row.findings,
    )


def _verdict_view(row: FitVerdict, role_model: RoleModel | None) -> VerdictView:
    return VerdictView(
        id=row.id,
        role_model_id=row.role_model_id,
        role_model_code=role_model.code if role_model is not None else "",
        role_model_name=role_model.name if role_model is not None else "",
        cost=role_model.cost if role_model is not None else "",
        fit=row.fit,
        verdict=row.verdict,
        note=row.note,
        evidence=list(row.evidence),
        probe=dict(row.probe),
    )
