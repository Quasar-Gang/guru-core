"""Gather everything one plan session knows into a single, snapshottable context.

``SessionContext`` is what lands in ``plan_sessions.context_snapshot``, so it has to be
reproducible: no clock reads, no randomness, only what the repos hold. ``to_prompt_context``
turns it into the jinja variables the prompt templates in ``packages/llm/prompts`` expect.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

import yaml
from pydantic import BaseModel, ConfigDict

from packages.importers.document import DocEvent, TextChunk
from packages.llm.ports import Purpose
from packages.repo.entities import RoleModel
from packages.repo.ports import (
    DocumentRepo,
    FollowupRoundRepo,
    PlanSessionRepo,
    ProfileRepo,
    RoleModelRepo,
)
from services.plan_engine.application.ports import RoleModelRendererPort
from services.plan_engine.domain.capacity import Capacity
from services.plan_engine.domain.difficulty import Pacing
from services.plan_engine.domain.readiness import ReadinessConfig

__all__ = ["ContextBuilder", "SessionContext"]

#: How much of a text chunk survives into the summary line handed to the LLM.
_SUMMARY_CHARS = 200
#: Fallback role model context budget when the container passes no per-purpose budgets.
_DEFAULT_BUDGET_TOKENS = 300


class SessionContext(BaseModel):
    """Everything the evaluate and generate prompts need about one session."""

    model_config = ConfigDict(extra="forbid")

    goal: str
    intake: dict[str, Any]
    timezone: str
    profile_answers: dict[str, Any]
    documents_summary: list[str]
    existing_events: list[DocEvent]
    use_calendar: bool
    trait_context: str
    persona_context: str
    previous_rounds: list[dict[str, Any]]
    metrics_yaml: str

    # --- additions to the plan's field list, needed by the scheduler (PRD 4.3.2) ---
    capacity: Capacity
    """Availability the scheduler places tasks into; defaults to the standard day windows."""
    pacing: Pacing | None
    """Hard bounds from the trait role model, or None when no trait is attached."""
    asked_metric_ids: list[str]
    """Metric ids already asked in an earlier round; a rule forbids asking them again."""

    def to_prompt_context(self) -> dict[str, Any]:
        """The jinja variables shared by ``evaluate_readiness`` and ``generate_plans``."""
        return {
            "goal": self.goal,
            "intake": self.intake,
            "documents_summary": list(self.documents_summary),
            "existing_schedule": [_event_line(event) for event in self.existing_events],
            "trait_context": self.trait_context,
            "persona_context": self.persona_context,
            # The trait block rendered for Purpose.generate is exactly the pacing sentence
            # the generate prompt asks for under `pacing_context`.
            "pacing_context": self.trait_context,
            "previous_rounds": list(self.previous_rounds),
            "metrics_yaml": self.metrics_yaml,
        }


class ContextBuilder:
    """Read the session, profile, documents, follow-ups and role models into one context."""

    def __init__(
        self,
        sessions: PlanSessionRepo,
        profiles: ProfileRepo,
        documents: DocumentRepo,
        followups: FollowupRoundRepo,
        role_models: RoleModelRepo,
        renderer: RoleModelRendererPort,
        readiness: ReadinessConfig,
        *,
        budgets: Mapping[Purpose, int] | None = None,
    ) -> None:
        self._sessions = sessions
        self._profiles = profiles
        self._documents = documents
        self._followups = followups
        self._role_models = role_models
        self._renderer = renderer
        self._readiness = readiness
        self._budgets = dict(budgets or {})

    async def build(self, session_id: UUID, purpose: Purpose) -> SessionContext:
        session = await self._sessions.get_unscoped(session_id)
        if session is None:
            raise LookupError(f"unknown plan session {session_id}")

        profile = await self._profiles.get(session.user_id)
        timezone = profile.timezone if profile is not None else "UTC"
        profile_answers = dict(profile.answers) if profile is not None else {}

        documents = await self._documents.list_by_imports(session.import_ids)
        summary: list[str] = []
        events: list[DocEvent] = []
        for document in documents:
            summary.extend(_summary_lines(document.text_chunks))
            events.extend(_events(document.events))

        rounds = await self._followups.list_for_session(session_id)
        previous_rounds = [
            {
                "round_no": round_.round_no,
                "questions": list(round_.questions),
                "answers": list(round_.answers or []),
            }
            for round_ in rounds
        ]
        asked = [
            str(question.get("metric_id", ""))
            for round_ in rounds
            for question in round_.questions
            if question.get("metric_id")
        ]

        trait = await self._role_model(session.trait_role_model_id)
        persona = await self._role_model(session.persona_role_model_id)
        budget = self._budgets.get(purpose, _DEFAULT_BUDGET_TOKENS)

        return SessionContext(
            goal=session.goal,
            intake=dict(session.intake),
            timezone=timezone,
            profile_answers=profile_answers,
            documents_summary=summary,
            existing_events=events,
            use_calendar=session.use_calendar,
            trait_context=self._render(trait, purpose, budget),
            persona_context=self._render(persona, purpose, budget),
            previous_rounds=previous_rounds,
            metrics_yaml=_metrics_yaml(self._readiness),
            capacity=Capacity.default(timezone),
            pacing=_pacing(trait),
            asked_metric_ids=asked,
        )

    async def _role_model(self, role_model_id: UUID | None) -> RoleModel | None:
        if role_model_id is None:
            return None
        return await self._role_models.get(role_model_id)

    def _render(self, role_model: RoleModel | None, purpose: Purpose, budget: int) -> str:
        if role_model is None:
            return ""
        return self._renderer.to_context(
            role_model.kind, role_model.name, role_model.content, purpose, budget
        )


def _summary_lines(text_chunks: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for raw in text_chunks:
        try:
            chunk = TextChunk.model_validate(raw)
        except ValueError:
            continue
        text = " ".join(chunk.text.split())
        if not text:
            continue
        line = text if len(text) <= _SUMMARY_CHARS else f"{text[:_SUMMARY_CHARS]}…"
        lines.append(f"{chunk.section}: {line}" if chunk.section else line)
    return lines


def _events(raw_events: list[dict[str, Any]]) -> list[DocEvent]:
    events: list[DocEvent] = []
    for raw in raw_events:
        try:
            events.append(DocEvent.model_validate(raw))
        except ValueError:
            continue
    return events


def _event_line(event: DocEvent) -> str:
    if event.all_day:
        return f"{event.start_at.date().isoformat()} (all day) {event.title}"
    return (
        f"{event.start_at.isoformat()} - {event.end_at.time().isoformat(timespec='minutes')} "
        f"{event.title}"
    )


def _pacing(trait: RoleModel | None) -> Pacing | None:
    """Read ``content["pacing"]`` off the trait role model; ignore anything malformed."""
    if trait is None:
        return None
    raw = trait.content.get("pacing")
    if not isinstance(raw, dict):
        return None
    try:
        return Pacing.model_validate(raw)
    except ValueError:
        return None


def _metrics_yaml(readiness: ReadinessConfig) -> str:
    """Render the readiness config back to YAML; this text goes into the evaluate prompt."""
    text: str = yaml.safe_dump(
        readiness.model_dump(exclude_none=True),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    return text.strip()
