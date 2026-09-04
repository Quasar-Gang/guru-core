"""InMemoryFollowupRoundRepo — 測試用的記憶體實作。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from packages.repo.entities import FollowupRound


class InMemoryFollowupRoundRepo:
    """把 followup_rounds 放在 process 記憶體中的 FollowupRoundRepo 實作。"""

    def __init__(self) -> None:
        self._rounds: dict[UUID, FollowupRound] = {}

    async def create(
        self, session_id: UUID, round_no: int, questions: list[dict[str, Any]]
    ) -> FollowupRound:
        round_ = FollowupRound(
            id=uuid.uuid4(),
            session_id=session_id,
            round_no=round_no,
            questions=list(questions),
            answers=None,
            answered_at=None,
            created_at=datetime.now(UTC),
        )
        self._rounds[round_.id] = round_
        return round_

    async def latest(self, session_id: UUID) -> FollowupRound | None:
        rounds = await self.list_for_session(session_id)
        return rounds[-1] if rounds else None

    async def list_for_session(self, session_id: UUID) -> list[FollowupRound]:
        rounds = [r for r in self._rounds.values() if r.session_id == session_id]
        rounds.sort(key=lambda r: r.round_no)
        return rounds

    async def record_answers(
        self, round_id: UUID, answers: list[dict[str, Any]], answered_at: datetime
    ) -> None:
        round_ = self._rounds.get(round_id)
        if round_ is None:
            raise KeyError(round_id)
        self._rounds[round_id] = round_.model_copy(
            update={"answers": list(answers), "answered_at": answered_at}
        )
