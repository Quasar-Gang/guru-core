"""Plan endpoints: lifecycle (PRD 5), the built-in calendar / todo, and the daily check-in."""

from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status
from pydantic import BaseModel

from services.api.adapters.http.deps import CurrentUserId, get_container
from services.api.adapters.http.schemas import ErrorResponse
from services.api.application.create_revision import CreateRevisionResult
from services.api.application.get_plan import ExportStatusView, PlanDetail
from services.api.application.get_plan_session import PlanSummary
from services.api.application.get_revision import RevisionView
from services.api.application.list_checkins import CheckinHistory
from services.api.application.list_plan_tasks import PlanTaskList, PlanTaskView
from services.api.application.request_export import ExportRequestResult
from services.api.application.submit_checkin import CheckinResultInput, CheckinView

__all__ = [
    "CreateRevisionRequest",
    "RequestExportRequest",
    "SubmitCheckinRequest",
    "UpdatePlanRequest",
    "UpdatePlanTaskRequest",
    "router",
]

router = APIRouter(tags=["plans"])

_UNAUTHORIZED = (
    "`unauthorized` — the `Authorization: Bearer <jwt>` header is missing or malformed, or the "
    "token has expired."
)
_RATE_LIMITED = (
    "`rate_limited` — too many requests from this caller in the last minute. The response "
    "carries `Retry-After`."
)
_PLAN_NOT_FOUND = (
    "`not_found` — no plan with this id belongs to the caller. Another user's plan is "
    "indistinguishable from one that never existed."
)


def _errors(*entries: tuple[int, str]) -> dict[int | str, dict[str, Any]]:
    """Document one status per entry; every one of them uses the `{"error": ...}` envelope."""
    return {code: {"model": ErrorResponse, "description": text} for code, text in entries}


class UpdatePlanRequest(BaseModel):
    title: str | None = None
    status: str | None = None


@router.get(
    "/plans",
    response_model=list[PlanSummary],
    summary="List the caller's plans",
    response_description=(
        "One summary per plan: title, difficulty, status, dates, weekly load and completion rate."
    ),
    responses=_errors(
        (401, _UNAUTHORIZED),
        (422, "`invalid_input` — `status` is not one of `draft`, `active` or `archived`."),
        (429, _RATE_LIMITED),
    ),
)
async def list_plans(
    request: Request, user_id: CurrentUserId, status: str | None = None
) -> list[PlanSummary]:
    """The home screen's list: every plan the user owns, across all their sessions.

    **Without `status`, archived plans are hidden** — the default is "what I still work on", so
    `draft` (a generated variant not yet chosen) and `active` come back. Pass `status=archived`
    explicitly to show the archive; `status=draft` or `status=active` narrow to one bucket.

    Each entry carries `completion_rate` (`done / (done + missed + skipped)`, `0.0` for a plan
    nobody has touched) and the weekly load, so no per-plan call is needed to render the list.
    Use `GET /v1/plans/{plan_id}` for phases, progress detail and export state.
    """
    return await get_container(request).list_plans(user_id, status)


@router.get(
    "/plans/{plan_id}",
    response_model=PlanDetail,
    summary="Read one plan with its progress and export state",
    response_description=(
        "The plan's structure (`phases`, `success_criteria`, `assumptions`), its `progress` "
        "breakdown, and one `exports` row per target it has been pushed to."
    ),
    responses=_errors((404, _PLAN_NOT_FOUND), (401, _UNAUTHORIZED), (429, _RATE_LIMITED)),
)
async def get_plan(request: Request, user_id: CurrentUserId, plan_id: UUID) -> PlanDetail:
    """Everything one plan screen needs, except the individual tasks.

    - `phases` — the plan's stages, each with its focus and milestone.
    - `progress` — task counts by status, `completion_rate`, a `rate` per phase, and
      `checkpoints` (the milestone tasks with their due dates and current status).
    - `exports` — where this plan has been pushed and how far behind it is; `pending_changes` is
      the number of task edits waiting for the next incremental push.
    - `status` — `draft`, `active` or `archived`. See `PATCH /v1/plans/{plan_id}`.

    The scheduled tasks themselves come from `GET /v1/plans/{plan_id}/tasks`, which can be sliced
    to the date range on screen.
    """
    return await get_container(request).get_plan(user_id, plan_id)


@router.patch(
    "/plans/{plan_id}",
    response_model=PlanDetail,
    summary="Rename a plan, or move it through the lifecycle",
    response_description="The plan as it now stands, in the same shape as `GET /v1/plans/{id}`.",
    responses=_errors(
        (404, _PLAN_NOT_FOUND),
        (
            409,
            "`illegal_transition` — the requested move is not an edge of the lifecycle. In "
            "particular a plan cannot be set to the status it already has, and an `archived` "
            "plan can only go back to `active`, never straight to `draft`.",
        ),
        (
            422,
            "`invalid_input` — `title` is present but blank, or `status` is not one of `draft`, "
            "`active`, `archived`.",
        ),
        (401, _UNAUTHORIZED),
        (429, _RATE_LIMITED),
    ),
)
async def update_plan(
    request: Request, user_id: CurrentUserId, plan_id: UUID, body: UpdatePlanRequest
) -> PlanDetail:
    """Rename a plan, and — more importantly — **this is how the user picks a plan**.

    A finished session leaves three `draft` plans. Sending `{"status": "active"}` on one of them
    is the choice: it becomes the running plan, and **the other plans of the same session are
    pushed back to `draft` automatically** — a session never has two active plans.

    The lifecycle, and every legal move:

    | from | to |
    | --- | --- |
    | `draft` | `active`, `archived` |
    | `active` | `draft`, `archived` |
    | `archived` | `active` |

    Anything else — including re-sending the status a plan already has — is a `409`
    `illegal_transition`. Both fields are optional; omitting them both is a no-op read.

    Changing status never touches an exported calendar. Use
    `DELETE /v1/plans/{plan_id}/export/{target}` for that.
    """
    return await get_container(request).update_plan(
        user_id, plan_id, title=body.title, status=body.status
    )


@router.post(
    "/plans/{plan_id}/archive",
    response_model=PlanDetail,
    summary="Archive a plan",
    response_description="The archived plan, in the same shape as `GET /v1/plans/{id}`.",
    responses=_errors(
        (404, _PLAN_NOT_FOUND),
        (
            409,
            "`illegal_transition` — the plan is already `archived`; there is nothing to do.",
        ),
        (401, _UNAUTHORIZED),
        (429, _RATE_LIMITED),
    ),
)
async def archive_plan(request: Request, user_id: CurrentUserId, plan_id: UUID) -> PlanDetail:
    """Put a plan away without losing it — the shorthand for `PATCH` with `archived`.

    The plan and all its data stay; it simply drops out of the default `GET /v1/plans` listing
    and can be brought back with `PATCH /v1/plans/{plan_id}` (`{"status": "active"}`).

    **Archiving deliberately leaves an exported calendar alone**: events stay in Google Calendar
    until the plan is deleted, or the export is undone with
    `DELETE /v1/plans/{plan_id}/export/{target}`.
    """
    return await get_container(request).archive_plan(user_id, plan_id)


@router.delete(
    "/plans/{plan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a plan and everything attached to it",
    response_description="`204` with an empty body once the plan and its tasks are gone.",
    responses=_errors((404, _PLAN_NOT_FOUND), (401, _UNAUTHORIZED), (429, _RATE_LIMITED)),
)
async def delete_plan(request: Request, user_id: CurrentUserId, plan_id: UUID) -> Response:
    """Permanent, and it reaches outside the app — confirm with the user first.

    Every export is undone before the plan goes, so the plan's secondary Google Calendar and all
    its events are deleted too, along with the plan's tasks, check-ins and revisions. There is no
    undo; offer `POST /v1/plans/{plan_id}/archive` to anyone who only wants it out of the way.

    Removing the external calendar is best effort: a calendar the user already deleted, or a
    Google connection that has expired, does not block the deletion. Any status other than `204`
    means nothing was deleted.
    """
    await get_container(request).delete_plan(user_id, plan_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class UpdatePlanTaskRequest(BaseModel):
    status: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    missed_reason: str | None = None


class SubmitCheckinRequest(BaseModel):
    checkin_date: date
    results: list[CheckinResultInput] = []
    note: str | None = None


@router.get(
    "/plans/{plan_id}/tasks",
    response_model=PlanTaskList,
    summary="List a plan's scheduled tasks over a date range",
    response_description=(
        "`items` in schedule order plus `total`, the number of tasks in the requested range."
    ),
    responses=_errors(
        (404, _PLAN_NOT_FOUND),
        (422, "`invalid_input` — `from` or `to` is not an ISO `YYYY-MM-DD` date."),
        (401, _UNAUTHORIZED),
        (429, _RATE_LIMITED),
    ),
)
async def list_plan_tasks(
    request: Request,
    user_id: CurrentUserId,
    plan_id: UUID,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> PlanTaskList:
    """What the built-in calendar and todo list are drawn from.

    `from` and `to` are **local calendar dates in the plan owner's timezone** (the one on their
    profile, falling back to UTC), and **both ends are inclusive**: `from=2026-03-02&to=2026-03-08`
    is exactly that week, whatever the user's offset. Omit either end for an open range, or both
    for the whole plan.

    `start_at` / `end_at` come back as UTC instants — render them in the user's timezone.
    `all_day` marks tasks with no meaningful time of day (rest days and checkpoints). `synced`
    tells you whether this task's current state has reached the exported calendar; it flips to
    `false` on every edit and back to `true` after the next push.
    """
    return await get_container(request).list_plan_tasks(user_id, plan_id, from_, to)


@router.patch(
    "/plans/{plan_id}/tasks/{task_id}",
    response_model=PlanTaskView,
    summary="Tick off, reschedule, or annotate one task",
    response_description="The task after the change, including its refreshed `synced` flag.",
    responses=_errors(
        (
            404,
            "`not_found` — the plan does not belong to the caller, or the task does not belong "
            "to this plan.",
        ),
        (
            422,
            "`invalid_input` — `status` is not one of `pending`, `done`, `missed`, `skipped`, or "
            "the resulting `end_at` is not strictly after `start_at`.",
        ),
        (401, _UNAUTHORIZED),
        (429, _RATE_LIMITED),
    ),
)
async def update_plan_task(
    request: Request,
    user_id: CurrentUserId,
    plan_id: UUID,
    task_id: UUID,
    body: UpdatePlanTaskRequest,
) -> PlanTaskView:
    """One task at a time: the checkbox and the drag-and-drop of the calendar view.

    Every field is optional; only what is sent changes. Sending nothing returns the task
    untouched.

    - `status` — `pending`, `done`, `missed` or `skipped`. Moving to `done` stamps
      `completed_at`; moving back to `pending` clears it.
    - `start_at` / `end_at` — reschedule. Either may be sent alone, but the resulting interval
      must have `end_at` strictly after `start_at`, so a lone `start_at` that overruns the
      existing `end_at` is a 422.
    - `missed_reason` — free text kept alongside a missed task; it is what a later
      `postpone` / `reduce` revision explains itself with.

    Any accepted change marks the task out of sync and, **if the plan has been exported to Google
    Calendar, queues an incremental push automatically** — no export call is needed. The response
    is written before that push runs, so `synced` is `false` here and turns `true` once
    `GET /v1/plans/{plan_id}/export` reports `synced` again.

    To record a whole day at once, use `POST /v1/plans/{plan_id}/checkins` instead.
    """
    return await get_container(request).update_plan_task(
        user_id,
        plan_id,
        task_id,
        status=body.status,
        start_at=body.start_at,
        end_at=body.end_at,
        missed_reason=body.missed_reason,
    )


@router.post(
    "/plans/{plan_id}/checkins",
    response_model=CheckinView,
    summary="Submit the daily check-in",
    response_description="The stored check-in for that date, with the results as recorded.",
    responses=_errors(
        (404, _PLAN_NOT_FOUND),
        (
            422,
            "`invalid_input` — one of `results[].task_id` does not belong to this plan, or a "
            "`status` is not one of `done`, `missed`, `skipped` (`pending` is not a check-in "
            "outcome).",
        ),
        (401, _UNAUTHORIZED),
        (429, _RATE_LIMITED),
    ),
)
async def submit_checkin(
    request: Request, user_id: CurrentUserId, plan_id: UUID, body: SubmitCheckinRequest
) -> CheckinView:
    """Record how one day went, in a single call.

    `checkin_date` is a local calendar date, and there is **one check-in per plan per date**:
    submitting the same date again replaces the previous submission rather than adding to it, so
    an edited day should be re-sent in full.

    Each entry in `results` sets one task to `done`, `missed` or `skipped`, with an optional
    `reason` (stored as the task's `missed_reason`). The tasks are the real record — a check-in
    writes straight through to them, so the counts in `GET /v1/plans/{plan_id}` move with it —
    and, when the plan is exported to Google Calendar, an incremental push is queued for the
    tasks that changed.

    `results` may be empty: that stores a note-only check-in and touches no task.
    """
    return await get_container(request).submit_checkin(
        user_id, plan_id, body.checkin_date, body.results, body.note
    )


@router.get(
    "/plans/{plan_id}/checkins",
    response_model=CheckinHistory,
    summary="Read the check-in history and the daily completion curve",
    response_description=(
        "`items`, the check-ins as submitted, and `daily_rates`, one `done / total` point per "
        "check-in date."
    ),
    responses=_errors((404, _PLAN_NOT_FOUND), (401, _UNAUTHORIZED), (429, _RATE_LIMITED)),
)
async def list_checkins(request: Request, user_id: CurrentUserId, plan_id: UUID) -> CheckinHistory:
    """The progress screen: every check-in ever submitted for this plan, plus its curve.

    `daily_rates` is derived per check-in — `done` over how many tasks that day's submission
    covered — so it is a record of what the user reported, not of the plan as a whole. A day with
    no check-in has no point at all, and a note-only check-in scores `0.0` over `0` tasks.

    For the plan-wide numbers (overall completion, per-phase rates, checkpoints) read
    `GET /v1/plans/{plan_id}` instead.
    """
    return await get_container(request).list_checkins(user_id, plan_id)


class RequestExportRequest(BaseModel):
    target: str
    options: dict[str, Any] = {}


@router.post(
    "/plans/{plan_id}/export",
    response_model=ExportRequestResult,
    summary="Export a plan: Markdown inline, everything else queued",
    response_description=(
        "For `markdown`, `markdown` holds the rendered document and its download link. For every "
        "other target, `job_id` and `mode` describe the queued push and `markdown` is null."
    ),
    responses=_errors(
        (404, _PLAN_NOT_FOUND),
        (
            409,
            "Two different codes share this status. `conflict` — the plan is not `active`; only "
            "an active plan can be exported, so activate it with `PATCH /v1/plans/{plan_id}` "
            "first. `reauth_required` — a queued target needs Google, and the user has never "
            "connected it or the authorization has expired; send them through "
            "`/v1/integrations` and retry. This is checked up front, so the client is never left "
            "watching a job that was doomed from the start.",
        ),
        (
            422,
            "`invalid_input` — `target` is not one of `markdown`, `google_calendar`, "
            "`google_sheets`, `notion`, or the `options` object is not valid for the target "
            "(for `markdown`: `include_completed` must be a boolean, `from` / `to` ISO dates).",
        ),
        (401, _UNAUTHORIZED),
        (429, _RATE_LIMITED),
    ),
)
async def request_export(
    request: Request, user_id: CurrentUserId, plan_id: UUID, body: RequestExportRequest
) -> ExportRequestResult:
    """One entry point, **two very different behaviours depending on `target`**.

    `target: "markdown"` is **synchronous**. The document is rendered during this request and the
    `200` already carries it: `markdown.content` is the Markdown text (render or copy it straight
    away) and `markdown.download_url` is a pre-signed link to the stored file that **expires
    after about 15 minutes** — fetch it now, do not persist it. There is no `job_id`, nothing is
    queued, and nothing needs polling. `options` slices the document:
    `include_completed` (default `true`), and `from` / `to` as ISO dates.

    Every other target — `google_calendar`, `google_sheets`, `notion` — is **asynchronous**. The
    response carries `job_id` and `mode` (`full` the first time, `incremental` once the plan has
    a calendar of its own) and the work runs on the queue. Poll
    `GET /v1/plans/{plan_id}/export`, whose row moves `queued` → `synced` or `failed` (with
    `error`); `GET /v1/jobs/{job_id}` is a coarser view of the same push.

    Either way the plan must be `active` (409 otherwise), and a queued Google target needs a live
    Google connection, which is verified before anything is enqueued.
    """
    return await get_container(request).request_export(user_id, plan_id, body.target, body.options)


@router.get(
    "/plans/{plan_id}/export",
    response_model=list[ExportStatusView],
    summary="Check where each export target stands",
    response_description=(
        "One row per target this plan has been exported to — empty until the first export. "
        "Markdown never appears here."
    ),
    responses=_errors((404, _PLAN_NOT_FOUND), (401, _UNAUTHORIZED), (429, _RATE_LIMITED)),
)
async def get_export_status(
    request: Request, user_id: CurrentUserId, plan_id: UUID
) -> list[ExportStatusView]:
    """What to poll after a queued `POST /v1/plans/{plan_id}/export`.

    Each row carries `status` (`queued` while the push waits or runs, `synced` when it finished,
    `failed` with the reason in `error` — `reauth_required` there means the Google connection
    expired mid-push), `external_calendar_id` (the calendar the events live in),
    `last_synced_at`, and `pending_changes`: how many task edits are waiting for the next
    incremental push.

    An empty array means this plan has never been exported. Markdown exports are rendered inline
    and stored nowhere, so they are never listed.
    """
    return await get_container(request).get_export_status(user_id, plan_id)


@router.delete(
    "/plans/{plan_id}/export/{target}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Undo an export and delete the external calendar",
    response_description="`204` with an empty body once the export has been undone.",
    responses=_errors(
        (
            404,
            "`not_found` — the plan does not belong to the caller, or this plan has no export "
            "for `target` (nothing was ever pushed there, or it has already been undone).",
        ),
        (401, _UNAUTHORIZED),
        (429, _RATE_LIMITED),
    ),
)
async def unexport_plan(
    request: Request, user_id: CurrentUserId, plan_id: UUID, target: str
) -> Response:
    """Take the plan back out of the external service; the plan itself is untouched.

    `target` is the value from `GET /v1/plans/{plan_id}/export` — in practice `google_calendar`.
    **The whole secondary calendar is removed, not the events one by one**, every task forgets its
    external reference, and the export row disappears, so a later export starts a fresh `full`
    push.

    Deleting the remote calendar is best effort: a calendar the user already removed, or an
    expired Google connection, still leaves the local state cleaned up — a plan can never get
    stuck in an exported state it cannot leave.
    """
    await get_container(request).unexport_plan(user_id, plan_id, target)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class CreateRevisionRequest(BaseModel):
    strategy: str
    note: str | None = None


@router.post(
    "/plans/{plan_id}/revisions",
    response_model=CreateRevisionResult,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ask for a revision when the plan has slipped",
    response_description=(
        "Accepted. `revision_id` is the resource to poll; `job_id` identifies the queued "
        "`plan.revise` job."
    ),
    responses=_errors(
        (404, _PLAN_NOT_FOUND),
        (
            409,
            "`conflict` — either the plan is not `active` (only a running plan can be revised), "
            "or this plan **already has an open revision**: a plan may hold at most one undecided "
            "proposal, so accept or reject the existing one before asking for another. "
            "`GET /v1/plans/{plan_id}/revisions` shows which one is still `pending` or `proposed`.",
        ),
        (422, "`invalid_input` — `strategy` is not `postpone` or `reduce`."),
        (401, _UNAUTHORIZED),
        (429, _RATE_LIMITED),
    ),
)
async def create_revision(
    request: Request, user_id: CurrentUserId, plan_id: UUID, body: CreateRevisionRequest
) -> CreateRevisionResult:
    """Start a rescheduling proposal. **Nothing changes until the user accepts it.**

    Two strategies:

    - `postpone` — keep the workload, push the remaining schedule later (and the deadline with
      it); for someone who fell behind.
    - `reduce` — keep the dates, lighten the weekly load; for someone who cannot keep the pace.

    `note` is the user's own words about what went wrong; it is shown back until the engine
    replaces it with its own `rationale`.

    Requires an `active` plan, and **only one revision may be open at a time** — a second request
    while a proposal is still undecided is a `409`.

    This returns `202`: the proposal is computed on the queue. Poll
    `GET /v1/plans/{plan_id}/revisions/{revision_id}` until its `status` leaves `pending` for
    `proposed` (`diff` and `summary` now filled in) or `failed`, then show the diff and let the
    user accept or reject it.
    """
    return await get_container(request).create_revision(user_id, plan_id, body.strategy, body.note)


@router.get(
    "/plans/{plan_id}/revisions",
    response_model=list[RevisionView],
    summary="List every revision ever asked for on this plan",
    response_description="All revisions, oldest first, each with its full diff.",
    responses=_errors((404, _PLAN_NOT_FOUND), (401, _UNAUTHORIZED), (429, _RATE_LIMITED)),
)
async def list_revisions(
    request: Request, user_id: CurrentUserId, plan_id: UUID
) -> list[RevisionView]:
    """The plan's revision history, including the one still awaiting a decision.

    Oldest first. At most one entry is undecided (`status: "proposed"`), and that is the one
    blocking a new `POST /v1/plans/{plan_id}/revisions` — as is one still being computed
    (`pending`); the rest are `accepted`, `rejected` or `failed`. `decided_at` stays null
    until the user answers.
    """
    return await get_container(request).list_revisions(user_id, plan_id)


@router.get(
    "/plans/{plan_id}/revisions/{revision_id}",
    response_model=RevisionView,
    summary="Read one revision and its proposed diff",
    response_description=(
        "The revision's `status` and `rationale`, the per-task `diff`, and a `summary` counting "
        "the diff by kind."
    ),
    responses=_errors(
        (
            404,
            "`not_found` — the plan does not belong to the caller, or no revision with this id "
            "belongs to that plan.",
        ),
        (401, _UNAUTHORIZED),
        (429, _RATE_LIMITED),
    ),
)
async def get_revision(
    request: Request, user_id: CurrentUserId, plan_id: UUID, revision_id: UUID
) -> RevisionView:
    """Poll this after a `202` from `POST /v1/plans/{plan_id}/revisions`, then render the diff.

    While the engine is still working, `diff` is empty and `rationale` still holds the user's own
    note. Once `status` is `proposed`, `rationale` explains the proposal and `diff` lists the
    affected tasks, each with `before` / `after` snapshots and a `kind`: `added`, `moved`,
    `removed`, `shortened`, `lengthened`, `reduced` or `unchanged`. `summary` counts those kinds
    for a one-line headline ("3 moved, 1 removed").

    A `proposed` revision is a preview only — the plan's tasks are still the old ones until
    `POST .../accept`.
    """
    return await get_container(request).get_revision(user_id, plan_id, revision_id)


@router.post(
    "/plans/{plan_id}/revisions/{revision_id}/accept",
    response_model=RevisionView,
    summary="Accept a proposed revision and rewrite the schedule",
    response_description="The revision, now `accepted`, with `decided_at` set.",
    responses=_errors(
        (
            404,
            "`not_found` — the plan does not belong to the caller, or no revision with this id "
            "belongs to that plan.",
        ),
        (
            409,
            "`conflict` — the revision is not `proposed`: it is still being computed, it "
            "`failed`, or it has already been accepted or rejected (a decision is final). The "
            "same code is returned when a revision reached `proposed` carrying no proposal to "
            "apply.",
        ),
        (401, _UNAUTHORIZED),
        (429, _RATE_LIMITED),
    ),
)
async def accept_revision(
    request: Request, user_id: CurrentUserId, plan_id: UUID, revision_id: UUID
) -> RevisionView:
    """Apply the proposal. **This is the only thing that ever rewrites a plan's schedule.**

    Everything from **today onwards** is replaced by the proposed tasks; days already past keep
    their history, including what was ticked off. The plan's own fields follow the proposal too —
    `deadline`, `duration_weeks`, `goal_statement` and its structure — so re-read
    `GET /v1/plans/{plan_id}` and `GET /v1/plans/{plan_id}/tasks` afterwards rather than patching
    the client's copy.

    If the plan is exported to Google Calendar, an incremental push is queued automatically;
    watch `GET /v1/plans/{plan_id}/export` for it to land.

    The decision is final and frees the plan for a future revision; call it only on a revision
    whose `status` is `proposed`.
    """
    return await get_container(request).decide_revision(user_id, plan_id, revision_id, "accept")


@router.post(
    "/plans/{plan_id}/revisions/{revision_id}/reject",
    response_model=RevisionView,
    summary="Reject a proposed revision and keep the plan as is",
    response_description="The revision, now `rejected`, with `decided_at` set.",
    responses=_errors(
        (
            404,
            "`not_found` — the plan does not belong to the caller, or no revision with this id "
            "belongs to that plan.",
        ),
        (
            409,
            "`conflict` — the revision is not `proposed`: it is still being computed, it "
            "`failed`, or it has already been accepted or rejected (a decision is final).",
        ),
        (401, _UNAUTHORIZED),
        (429, _RATE_LIMITED),
    ),
)
async def reject_revision(
    request: Request, user_id: CurrentUserId, plan_id: UUID, revision_id: UUID
) -> RevisionView:
    """Turn the proposal down. The plan, its tasks and its exports are left exactly as they were.

    The revision is kept in the history as `rejected` — nothing is written to the plan — and the
    plan is free to be revised again, so the user can immediately ask for the other strategy with
    `POST /v1/plans/{plan_id}/revisions`.
    """
    return await get_container(request).decide_revision(user_id, plan_id, revision_id, "reject")
