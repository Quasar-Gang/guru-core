"""Queue consumers: unwrap a payload, call the use case. No logic beyond that."""

from packages.queue.jobs import (
    DirectionRunJobV1,
    JobPayload,
    PlanGenerateJobV1,
    ProfileBuildJobV1,
    ReconcileJobV1,
)
from services.engine.application.build_profile import BuildProfile
from services.engine.application.generate_plan import GeneratePlan
from services.engine.application.reconcile import Reconcile
from services.engine.application.run_direction import RunDirection

__all__ = [
    "DirectionRunConsumer",
    "PlanGenerateConsumer",
    "ProfileBuildConsumer",
    "ReconcileConsumer",
]


class ProfileBuildConsumer:
    def __init__(self, build_profile: BuildProfile) -> None:
        self._build_profile = build_profile

    async def __call__(self, payload: JobPayload) -> None:
        assert isinstance(payload, ProfileBuildJobV1)
        await self._build_profile(payload.user_id)


class DirectionRunConsumer:
    def __init__(self, run_direction: RunDirection) -> None:
        self._run_direction = run_direction

    async def __call__(self, payload: JobPayload) -> None:
        assert isinstance(payload, DirectionRunJobV1)
        await self._run_direction(payload.run_id)


class PlanGenerateConsumer:
    def __init__(self, generate_plan: GeneratePlan) -> None:
        self._generate_plan = generate_plan

    async def __call__(self, payload: JobPayload) -> None:
        assert isinstance(payload, PlanGenerateJobV1)
        await self._generate_plan(payload.plan_id)


class ReconcileConsumer:
    def __init__(self, reconcile: Reconcile) -> None:
        self._reconcile = reconcile

    async def __call__(self, payload: JobPayload) -> None:
        assert isinstance(payload, ReconcileJobV1)
        await self._reconcile(payload.reconciliation_id)
