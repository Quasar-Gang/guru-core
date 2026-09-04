"""The single entry point for every export target (PRD 3.5 / 4.3.4 / 4.3.5 / 5).

Markdown is produced inline; everything else is queued as an `export.push` job, in `full`
mode until the plan has a calendar of its own and `incremental` from then on.
"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError

from packages.queue import ExportJobV1, QueuePort
from packages.repo import PlanExportRepo
from services.api.application.export_markdown import ExportMarkdown, MarkdownExportResult
from services.api.application.get_plan import GetPlan
from services.api.application.google_access_token import GoogleAccessTokenProvider
from services.api.domain.errors import Conflict, InvalidInput
from services.api.domain.markdown_export import MarkdownOptions
from services.api.domain.plan_status import PlanStatus

__all__ = ["MARKDOWN_TARGET", "QUEUED_TARGETS", "ExportRequestResult", "RequestExport"]

MARKDOWN_TARGET = "markdown"

#: The targets that go through the `export.push` queue; they mirror `ExportJobV1.target`.
QUEUED_TARGETS = ("google_calendar", "google_sheets", "notion")

STATUS_QUEUED = "queued"


class ExportRequestResult(BaseModel):
    """Either an inline Markdown document, or the handle of the queued push."""

    target: str
    mode: str | None = None
    job_id: str | None = None
    markdown: MarkdownExportResult | None = None


class RequestExport:
    """Only an `active` plan can be exported (PRD 3.5)."""

    def __init__(
        self,
        get_plan: GetPlan,
        exports: PlanExportRepo,
        queue: QueuePort,
        tokens: GoogleAccessTokenProvider,
        export_markdown: ExportMarkdown,
    ) -> None:
        self._get_plan = get_plan
        self._exports = exports
        self._queue = queue
        self._tokens = tokens
        self._export_markdown = export_markdown

    async def __call__(
        self, user_id: UUID, plan_id: UUID, target: str, options: dict[str, Any]
    ) -> ExportRequestResult:
        plan = await self._get_plan.load(user_id, plan_id)
        if plan.status != PlanStatus.active.value:
            raise Conflict(f"only an active plan can be exported; this one is {plan.status}")

        if target == MARKDOWN_TARGET:
            markdown = await self._export_markdown(user_id, plan_id, _markdown_options(options))
            return ExportRequestResult(target=target, markdown=markdown)

        if target not in QUEUED_TARGETS:
            raise InvalidInput(f"unknown export target: {target}")

        # Fails fast with ReauthRequired when Google is not connected, so the client can
        # prompt for the connection instead of watching a queued job fail (PRD 3.6).
        await self._tokens.get(user_id)

        record = await self._exports.get(plan_id, target)
        calendar_id = record.external_calendar_id if record is not None else None
        mode = "incremental" if calendar_id else "full"
        await self._exports.upsert(
            plan_id,
            target,
            STATUS_QUEUED,
            calendar_id,
            record.last_synced_at if record is not None else None,
            None,
        )
        handle = await self._queue.enqueue(
            ExportJobV1.model_validate({"plan_id": plan_id, "target": target, "mode": mode})
        )
        return ExportRequestResult(target=target, mode=mode, job_id=handle.job_id)


def _markdown_options(options: dict[str, Any]) -> MarkdownOptions:
    try:
        return MarkdownOptions.model_validate(options)
    except ValidationError as exc:
        raise InvalidInput(f"invalid markdown export options: {exc.errors()}") from exc
