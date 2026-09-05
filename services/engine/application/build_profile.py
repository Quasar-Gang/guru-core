"""`profile.build` — turn everything the user has uploaded into the one Profile they have.

The model is asked for exactly one thing: which dimension each event belongs to, and what
the resume repeats. Coverage is arithmetic and is computed here, so the Profile can never
claim more than the data supports.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from packages.llm.ports import LLMPort, Purpose
from packages.llm.validation import BusinessRule, complete_validated
from packages.repo.entities import Profile
from packages.repo.ports import DocumentRepo, ImportRepo, ProfileRepo, QuestionAnswerRepo
from services.engine.application.documents import Uploads, event_ref, load_uploads
from services.engine.domain.dimensions import ReportDimensionsConfig
from services.engine.domain.profile import (
    ProfileSignals,
    ProfileSignalsOutput,
    build_coverage,
)

__all__ = ["BuildProfile"]

_TIMEZONE_FALLBACK = "UTC"


class BuildProfile:
    """One Profile per user, revised in place. Never a second one."""

    def __init__(
        self,
        imports: ImportRepo,
        documents: DocumentRepo,
        profiles: ProfileRepo,
        answers: QuestionAnswerRepo,
        llm: LLMPort,
        dimensions: ReportDimensionsConfig,
        max_attempts: int,
    ) -> None:
        self._imports = imports
        self._documents = documents
        self._profiles = profiles
        self._answers = answers
        self._llm = llm
        self._dimensions = dimensions
        self._max_attempts = max_attempts

    async def __call__(self, user_id: UUID) -> Profile:
        uploads = await load_uploads(self._imports, self._documents, user_id)
        existing = await self._profiles.get(user_id)
        timezone = existing.timezone if existing is not None else _TIMEZONE_FALLBACK

        if not uploads.document.events and not uploads.document.text_chunks:
            # Nothing to read yet. Record the empty coverage rather than inventing a read:
            # the Reports screen is allowed to say "there is not enough here".
            return await self._profiles.upsert(
                user_id,
                timezone,
                {},
                build_coverage(uploads.document, uploads.sources).model_dump(mode="json"),
                uploads.import_ids,
            )

        refs = {event_ref(index, event) for index, event in enumerate(uploads.document.events)}
        outcome = await complete_validated(
            self._llm,
            "build_profile",
            await self._context(user_id, uploads, timezone),
            ProfileSignalsOutput,
            Purpose.analyze,
            max_attempts=self._max_attempts,
            rules=[_known_refs(refs)],
            # An unusable classification is still better than no Profile: everything the
            # model failed to place simply counts as unclassified, which is a real answer.
            fallback=lambda _violations: ProfileSignalsOutput(
                signals=ProfileSignals(timezone=timezone)
            ),
        )
        signals = outcome.value.signals
        return await self._profiles.upsert(
            user_id,
            signals.timezone or timezone,
            signals.model_dump(mode="json"),
            build_coverage(uploads.document, uploads.sources).model_dump(mode="json"),
            uploads.import_ids,
        )

    async def _context(self, user_id: UUID, uploads: Uploads, timezone: str) -> dict[str, Any]:
        answered = await self._answers.list_for_user(user_id)
        return {
            "timezone": timezone,
            "dimensions": [spec.model_dump() for spec in self._dimensions.dimensions],
            "events": [
                {
                    "ref": event_ref(index, event),
                    "title": event.title,
                    "start": event.start_at.isoformat(),
                    "all_day": event.all_day,
                }
                for index, event in enumerate(uploads.document.events)
            ],
            "text_chunks": [chunk.text for chunk in uploads.document.text_chunks],
            "answers": [
                {"question": row.question_key, "text": row.answer}
                for row in answered
                if not row.skipped
            ],
        }


def _known_refs(refs: set[str]) -> BusinessRule:
    """Every classified event must point at an event we actually handed over."""

    def rule(output: Any) -> list[str]:
        if not isinstance(output, ProfileSignalsOutput):
            return []
        return [
            f"source_ref {item.source_ref!r} is not one of the events given"
            for item in output.signals.events
            if item.source_ref not in refs
        ]

    return rule
