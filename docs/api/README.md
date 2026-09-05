# API guide

The call sequence behind each part of the product, with runnable examples. The exhaustive
reference is [`openapi.json`](openapi.json) / [`openapi.yaml`](openapi.yaml), and Swagger UI
and ReDoc are served live at `/docs` and `/redoc`.

Everything below assumes:

```bash
API=http://127.0.0.1:8000
TOKEN=...            # from POST /v1/auth/google
AUTH="authorization: Bearer $TOKEN"
```

---

## Contents

- [The shape of every call](#the-shape-of-every-call)
- [1 · Sign in](#1--sign-in)
- [2 · Bring the data in](#2--bring-the-data-in)
- [3 · Read it](#3--read-it)
- [4 · Score every shape](#4--score-every-shape)
- [5 · The three questions](#5--the-three-questions)
- [6 · Settle on a direction](#6--settle-on-a-direction)
- [7 · The plan](#7--the-plan)
- [8 · Put it on the calendar](#8--put-it-on-the-calendar)
- [9 · The quarterly review](#9--the-quarterly-review)
- [Polling](#polling)

---

## The shape of every call

**Authentication.** Everything except `POST /v1/auth/google`, `GET /health` and the
presigned `/v1/files/*` routes needs `Authorization: Bearer <jwt>`.

**Errors.** Every failure, validation included, comes back in one envelope:

```json
{ "error": { "code": "not_found", "message": "plan not found: 0f3e…" } }
```

Branch on `code`, never on `message` — the message is for developers and is not stable.
The codes are the snake_case names of the domain errors:

| code | HTTP | Means |
|---|---|---|
| `invalid_input` | 422 | The body or a path value is wrong. Also every validation failure. |
| `unauthorized` | 401 | The bearer token is missing, malformed or expired. |
| `forbidden` | 403 | Authenticated, but not allowed to do this. |
| `not_found` | 404 | No such resource **for this caller**. |
| `conflict` | 409 | The current state does not allow it: a second run in flight, a draft plan being exported, a review answered twice. |
| `reauth_required` | 409 | The Google grant is gone; reconnect and retry. |
| `rate_limited` | 429 | Too many requests this minute. The response carries `Retry-After`. |

**Ownership reads as absence.** Another user's plan, run or hypothesis returns `404`, not
`403`. Existence is itself information.

**Long-running work returns `202`.** Analysis, plan generation, import parsing,
reconciliation and calendar export all run on a queue. Poll the resource, not the job — see
[Polling](#polling).

`GET /health` is unauthenticated and exempt from rate limiting.

---

## 1 · Sign in

```bash
curl -sX POST "$API/v1/auth/google" -H 'content-type: application/json' \
  -d '{"code": "<google authorization code>", "redirect_uri": "http://localhost:3000/cb"}'
```

```json
{ "access_token": "eyJ…", "token_type": "bearer", "user_id": "…", "email": "…", "is_new_user": true }
```

`GET /v1/me` echoes the caller back, which is the cheapest way to check a token is still
good.

Sign-in and calendar access are **separate grants**. Signing in asks for identity only; the
calendar consent is `GET /v1/integrations/{provider}/authorize` →
`POST /v1/integrations/{provider}/callback`, and `GET /v1/integrations` lists what is
connected. `DELETE /v1/integrations/{provider}` revokes it with Google and forgets the
token. The app never holds a Google token — only our JWT.

---

## 2 · Bring the data in

Two sources are enough to begin: a calendar and a résumé. A card statement is optional and
can be added later.

**A file, in three calls.**

```bash
# 1. reserve an import and get a direct-upload URL (valid 15 minutes, max 20 MB)
PRESIGN=$(curl -sX POST "$API/v1/imports/presign" -H "$AUTH" -H 'content-type: application/json' \
  -d '{"filename": "resume.pdf", "content_type": "application/pdf", "size_bytes": 214000}')
UPLOAD_URL=$(jq -r .upload_url <<<"$PRESIGN")
IMPORT=$(jq -r .import_id <<<"$PRESIGN")

# 2. PUT the bytes to upload_url as-is, with no Authorization header:
#    the URL carries its own signature
curl -sX PUT "$UPLOAD_URL" -H 'content-type: application/pdf' --data-binary @resume.pdf

# 3. confirm and queue the parse
curl -sX POST "$API/v1/imports/$IMPORT/complete" -H "$AUTH"
```

Supported formats: `csv`, `xlsx`, `md`, `html`, `pdf`, `docx`, `ics`. The format is decided
at presign time from the extension first, so a file that would be rejected is rejected
before it is uploaded. `PUT /v1/files/{key}` and `GET /v1/files/{key}` are the presigned
endpoints the local storage backend serves; with Cloudflare R2 the URL points there instead.

**A connected calendar, in one call.**

```bash
curl -sX POST "$API/v1/imports/google-calendar" -H "$AUTH" \
  -H 'content-type: application/json' -d '{"days": 90}'
```

There is no blob to keep, so this writes the document directly and lands as `parsed`.

`GET /v1/imports` lists everything with its status and counts. Every finished parse re-queues
the Profile build — the Profile is revised in place, never duplicated.

---

## 3 · Read it

```bash
curl -s "$API/v1/profile" -H "$AUTH"
```

```json
{
  "timezone": "Asia/Taipei",
  "signals": { "events": [...], "skills": [...], "roles": [...] },
  "coverage": { "sources": ["upload"], "events": 448, "period_start": "2025-10-06", "weeks": 26 }
}
```

`signals` is what the classifier decided; `coverage` is what arithmetic counted. Both are
empty until something has been uploaded, and that is a normal answer rather than an error.

---

## 4 · Score every shape

```bash
RUN=$(curl -sX POST "$API/v1/direction/runs" -H "$AUTH" | jq -r .id)   # 202
curl -s "$API/v1/direction/runs/latest" -H "$AUTH"
```

`status` moves `pending` → `analyzing` → `recommending` → `ready`. The reports are readable
as soon as it reaches `recommending`: the data is meant to speak before any shape is
proposed. `GET /v1/direction/runs/{run_id}` reads an earlier run, whose reports are the
baseline the quarterly review compares against.

```json
{
  "status": "ready",
  "readouts": { "trajectory": "…", "continuity": "…", "unclassified": "…" },
  "reports": [{ "dimension": "work", "metrics": { "hours": 812.5, "share": 0.62 }, "findings": {…} }],
  "verdicts": [{
    "role_model_code": "S-1",
    "fit": "strongly_consistent",
    "verdict": "Depth is accumulating, but nobody outside can see it.",
    "evidence": [{ "stance": "for", "text": "…", "cites": { "dimension": "work", "fact": "…" } }],
    "probe": { "statement": "…", "cost": "Once this quarter, about three evenings." }
  }]
}
```

Three things a client can rely on, because they are validated before the row is written:
every shape in the catalogue is scored, every verdict carries **exactly five** evidence
items with at least one `for` and one `against`, and every item cites a dimension that has a
report in this run.

`GET /v1/role-models` is the catalogue itself — the shipped six plus anything this user
wrote. `POST /v1/role-models` writes your own; `cost` is required, and a blank one is a
`422`.

A run is refused with `409` when nothing has been uploaded, or when one is already in
flight.

---

## 5 · The three questions

```bash
curl -s "$API/v1/questions" -H "$AUTH"
curl -sX PUT "$API/v1/questions/q1" -H "$AUTH" -H 'content-type: application/json' \
  -d '{"answer": "No more managing a team."}'
curl -sX PUT "$API/v1/questions/q2" -H "$AUTH" -H 'content-type: application/json' \
  -d '{"skipped": true}'
curl -sX PUT "$API/v1/questions/q3" -H "$AUTH" -H 'content-type: application/json' \
  -d '{"answer": "career"}'
```

All three are always returned, each with the reason it is being asked, and each is
skippable. Skipping is recorded as an answer rather than as an omission.

`q3` is a forced choice between `career`, `relationships` and `health`; anything else is a
`422`. Answering it writes the quota, readable at `GET /v1/quota`:

```json
{ "drop_first": "career", "weekly_minutes": 300 }
```

An answer is personal data, so it goes back to the Uploader rather than forward: it changes
the Profile, the Reports and every verdict downstream. Run the direction pass again to see
the verdicts move.

---

## 6 · Settle on a direction

```bash
curl -sX POST "$API/v1/hypotheses" -H "$AUTH" -H 'content-type: application/json' \
  -d '{"fit_verdict_id": "…"}'
```

```json
{ "version": 0, "role_model_code": "S-1", "review_date": "2026-06-05", "plan_id": "…" }
```

This writes `v0` and creates its plan in status `generating`. There is **no update route**,
and no repository method behind one: a hypothesis you could quietly edit could never be
falsified. `GET /v1/hypotheses` returns every version oldest first;
`GET /v1/hypotheses/{hypothesis_id}` returns one, with the `evidence_snapshot` it was built
on — a copy, so a re-run of the verdicts cannot change what was predicted.

---

## 7 · The plan

```bash
curl -s "$API/v1/plans" -H "$AUTH"
curl -s "$API/v1/plans/$PLAN" -H "$AUTH"
```

`status` starts at `generating` and becomes `draft`, or `failed` with an `error`. The detail
carries `milestones` as a **nested tree** and `structure` with the success criteria, the
assumptions, the quota, and anything the quota trimmed or the scheduler could not place.
Read `structure.assumptions` before showing anything: a plan that hides what it assumed is
lying about the week it just proposed.

```bash
curl -sX PUT "$API/v1/plans/$PLAN/status" -H "$AUTH" \
  -H 'content-type: application/json' -d '{"status": "active"}'
```

A plan is started or archived; it is never edited into something else. Wanting a different
plan means wanting a different hypothesis.

```bash
curl -s "$API/v1/plans/$PLAN/tasks?start_from=2026-03-09T00:00:00Z&start_to=2026-03-16T00:00:00Z" -H "$AUTH"
curl -sX PUT "$API/v1/plans/$PLAN/tasks/$TASK/status" -H "$AUTH" \
  -H 'content-type: application/json' -d '{"status": "done"}'
```

Tasks come back **flat**, in schedule order, each with the slot it was placed in — the task
says what the work is, the slot says when. Milestones nest and tasks do not, which is what
keeps "done" meaning the same thing everywhere.

```bash
curl -sX POST "$API/v1/plans/$PLAN/checkins" -H "$AUTH" -H 'content-type: application/json' \
  -d '{"checkin_date": "2026-03-09", "results": [{"task_id": "…", "status": "done"}]}'
curl -s "$API/v1/plans/$PLAN/checkins" -H "$AUTH"
```

One row per plan and day; re-submitting the same day replaces it. Statuses are written
straight through to the tasks, so there is exactly one place that says what happened.
`daily_rates` gives the completion curve.

---

## 8 · Put it on the calendar

```bash
curl -sX POST "$API/v1/plans/$PLAN/exports" -H "$AUTH" \
  -H 'content-type: application/json' -d '{"target": "google_calendar"}'   # 202
curl -s "$API/v1/plans/$PLAN/exports" -H "$AUTH"
curl -sX DELETE "$API/v1/plans/$PLAN/exports/google_calendar" -H "$AUTH"   # 204
```

Only an `active` plan is exported. The first push builds the plan its own secondary calendar
(`mode: full`); later ones replay only what changed (`mode: incremental`), and
`pending_changes` is exactly what the next push would send. Deleting the export removes the
calendar and forgets every event id — the database stays authoritative throughout, so losing
the calendar loses nothing.

`reauth_required` means the Google grant is gone; reconnect and try again.

---

## 9 · The quarterly review

```bash
REVIEW=$(curl -sX POST "$API/v1/reconciliations" -H "$AUTH" \
  -H 'content-type: application/json' -d '{"hypothesis_id": "…"}' | jq -r .id)   # 202
curl -s "$API/v1/reconciliations/$REVIEW" -H "$AUTH"
```

```json
{
  "status": "done",
  "comparison": { "execution": { "planned": 48, "done": 31, "completion": 0.646 }, "shifts": [...] },
  "narrative": "…",
  "revision_kind": "growth",
  "outcome": null
}
```

`outcome` is `null` on purpose. The comparison is arithmetic and the narrative explains it;
the decision is yours:

```bash
curl -sX PUT "$API/v1/reconciliations/$REVIEW/decision" -H "$AUTH" \
  -H 'content-type: application/json' -d '{"outcome": "revise"}'
```

`holds` keeps the shape. `revise` appends the next version of the hypothesis and returns its
id as `next_hypothesis_id`, leaving the previous version untouched. `replace` means starting
Station 1 again from the data.

`revision_kind` classifies a changed plan rather than punishing it: scope that moved because
something was learned is `growth`, scope that shrank at the first resistance is `avoidance`.
That distinction is what `q2` was collected for.

---

## Polling

`GET /v1/jobs/{job_id}` reports `queued`, `running`, `done`, `failed` or `unknown`.

**`unknown` is not an error.** Job records are short-lived because Redis is only a cache
here, so a job that finished a while ago reports `unknown` rather than `done`. Treat this
endpoint as a hint and render the resource instead:

| Work | Poll |
|---|---|
| Import parsing | `GET /v1/imports` — `status` |
| Profile build | `GET /v1/profile` — `coverage` |
| Analysis and scoring | `GET /v1/direction/runs/latest` — `status`, `error` |
| Plan generation | `GET /v1/plans/{plan_id}` — `status`, `error` |
| Reconciliation | `GET /v1/reconciliations/{id}` — `status`, `error` |
| Calendar export | `GET /v1/plans/{plan_id}/exports` — `status`, `error` |

PostgreSQL is the source of truth for all of it.
