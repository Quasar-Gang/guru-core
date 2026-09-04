# Plan Engine

Turns a goal into three executable plans. It is a worker-side service: it has no HTTP surface
of its own and is driven entirely by queue jobs (`plan.generate`, `plan.continue`, and from
Task 36 `plan.revise`).

## What it owns

- **The plan session state machine** (PRD 3.1): `collecting → evaluating → questioning →
  generating → done | failed`. `plan_sessions.status` in PostgreSQL is the authority; Redis
  only mirrors it under `session:{id}:status` (TTL 1 hour) so the API can serve polling
  cheaply.
- **Readiness evaluation and follow-up questions** (PRD 3.4, 13): whether the information on
  hand is enough to plan, and — when it is not — at most two rounds of at most five
  context-specific questions.
- **Plan generation** (PRD 4.3): one baseline `PlanTemplate` from the LLM, three difficulty
  variants derived in code from `config/difficulty_coefficients.yaml`, and the deterministic
  scheduler that expands each variant into `plan_tasks` with absolute times.
- **The business-rule half of the LLM validation chain** (PRD 7.5): a template that parses is
  not necessarily one that can be scheduled, so every candidate is run through the scheduler
  against the trait pacing and the breaches are fed back to the model. When the retries run
  out, the conservative default (3 × 40 minutes a week, three phases, twelve weeks) is used
  and the fact is recorded in the plan's `assumptions`.
- **`plans` and `plan_tasks` rows** for a session: three drafts sharing one `goal_statement`
  and one set of `success_criteria`.

## The ports it exposes

The service consumes ports rather than exposing them; the ones it defines itself live in
`application/ports.py`:

| Port | Purpose | Implementations |
| --- | --- | --- |
| `ClockPort` | current time, always timezone-aware UTC | `SystemClock`, `FakeClock` (both in `container.py`) |
| `RoleModelRendererPort` | render `role_models.content` into a markdown context block for one `Purpose` and token budget (PRD 12.6) | `NullRoleModelRenderer` today; Task 29 adds the real adapter |

`RoleModelRendererPort` is deliberately a local declaration. The Role Model service owns the
real renderer, but services must not import each other, so the two sides are bound by the
shape of `role_models.content` — the same arrangement as the duplicated `Pacing` model in
`domain/difficulty.py`.

Everything else comes from `packages/`: `PlanSessionRepo`, `FollowupRoundRepo`, `PlanRepo`,
`PlanTaskRepo`, `PlanRevisionRepo`, `DocumentRepo`, `RoleModelRepo`, `ProfileRepo`,
`LlmCallRepo`, `CachePort`, and `LLMPort`.

The use cases themselves are the callable entry points, wired in `container.py`:

- `EvaluateSession(job: PlanGenerateJobV1 | PlanContinueJobV1) -> None`
- `GeneratePlans(session_id, *, forced_missing=(), degraded=False) -> list[UUID]`

## What it does not do

- **No HTTP.** Creating a session, polling its status and submitting answers are API Service
  endpoints (Task 24); this service only reacts to queue jobs.
- **No queue or worker wiring.** The ARQ consumers and `cmd/plan_engine_worker.py` arrive in
  Task 24; the use cases know nothing about ARQ.
- **No role model curation, scoring or recommendation.** That is the Role Model service; the
  Plan Engine only reads `role_models` rows and renders them through the port above.
- **No export.** Google Calendar, Sheets, Notion and Markdown exports belong to the API
  service.
- **No date arithmetic by the LLM.** The model never sees or emits an absolute date; the
  scheduler in `domain/scheduler.py` owns that, and the difficulty variants are derived from
  coefficients rather than generated (PRD 7.6).
