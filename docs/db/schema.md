# Database schema

Twenty tables in one PostgreSQL database, shared by three services. Every table names one
owner in `packages/repo/models.py`: only the owner writes it, everyone else reads. That is
what lets the services stay independent without a network hop between them.

The schema follows the three stations, and four rules are enforced here rather than
documented as hopes:

| Rule | Enforced by |
|---|---|
| One Profile per user | `profiles.user_id` **is** the primary key |
| Milestones nest; Tasks do not | `tasks.milestone_id` is `NOT NULL`, and there is no `tasks.parent_id` |
| A hypothesis is never overwritten | `uq_hypothesis_user_version`, and no repository exposes an update |
| Every Role Model states its cost | `role_models.cost` is `NOT NULL`, and the domain rejects a blank one |

Every id is a `uuid` with a server-side default. Timestamps are `timestamptz`; dates that
name a day rather than a moment — a review date, a check-in — are `date`.

There is exactly one migration, `the three stations`. The previous schema described a
different product and no production data depended on it, so it was squashed rather than
evolved through a chain of renames.

---

## Contents

- [Identity and intake](#identity-and-intake) — `users` · `oauth_connections` · `imports` · `documents` · `profiles`
- [Station 1 · analysis and direction](#station-1--analysis-and-direction) — `direction_runs` · `reports` · `role_models` · `fit_verdicts` · `question_answers` · `quotas` · `direction_hypotheses`
- [Station 2 · the plan](#station-2--the-plan) — `plans` · `milestones` · `tasks` · `schedule_slots` · `checkins` · `plan_exports`
- [Station 3 · reconciliation](#station-3--reconciliation) — `reconciliations`
- [Cross-cutting](#cross-cutting) — `llm_calls`

---

## Identity and intake

### `users`

Owner: **API Service**.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `email` | varchar(320) | unique |
| `google_sub` | varchar(128) | unique; the stable Google subject, not the address |
| `created_at` | timestamptz | |

The subject is what identity is keyed on, because an email can change hands.

### `oauth_connections`

Owner: **API Service**. Sign-in and calendar access are separate grants; this table holds
the second one.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `user_id` | uuid | FK → `users`, cascade |
| `provider` | varchar(32) | unique with `user_id` |
| `encrypted_refresh_token` | bytea | Fernet; a refresh token is never stored in the clear |
| `scopes` | text | space-separated, as Google returns them |
| `expires_at` | timestamptz | nullable |
| `revoked_at` | timestamptz | set when Google rejects the grant |
| `created_at` | timestamptz | |

### `imports`

Owner: **API Service**. One upload of personal data.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `user_id` | uuid | FK → `users`, cascade |
| `source` | varchar(32) | `upload` · `google_calendar` |
| `format` | varchar(16) | decided at presign time, never re-sniffed |
| `storage_key` | text | empty for a calendar pull: there is no blob |
| `filename` | text | reduced to a single path segment |
| `status` | varchar(16) | `pending` → `queued` → `parsed` \| `failed` |
| `error` | text | why a parse failed; a queue retry would hit the same file |
| `created_at` | timestamptz | |

### `documents`

Owner: **API Service**. The Uploader's normalized read of one import.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `import_id` | uuid | FK → `imports`, cascade, **unique** — one document per import |
| `events` | jsonb | `DocEvent[]`: title, start, end, all-day, source ref |
| `text_chunks` | jsonb | `TextChunk[]`: text with no time information |
| `created_at` | timestamptz | |

### `profiles`

Owner: **Engine**. What the personal data adds up to.

| Column | Type | Notes |
|---|---|---|
| `user_id` | uuid | **PK**, FK → `users`, cascade |
| `timezone` | varchar(64) | IANA; the only thing sign-in can honestly record |
| `signals` | jsonb | the classifier's output: classified events, skills, roles |
| `coverage` | jsonb | computed in code: counts, sources, the period covered |
| `source_import_ids` | jsonb | which imports this read was built from |
| `updated_at` | timestamptz | |

**One per user, revised in place.** Making `user_id` the primary key means a second Profile
cannot be written even by mistake — the invariant is the schema, not a convention.

The split inside is the rule the whole pipeline follows: `signals` is what a model decided,
`coverage` is what arithmetic counted. Nothing countable is ever taken from a model.

---

## Station 1 · analysis and direction

### `direction_runs`

Owner: **API Service** creates rows; the **Engine** owns the transitions. One pass of the
concept model's steps 3-8a.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `user_id` | uuid | FK → `users`, cascade |
| `status` | varchar(16) | `pending` → `analyzing` → `recommending` → `ready` \| `failed` |
| `period_start` | date | the window the reports cover |
| `period_end` | date | |
| `readouts` | jsonb | the six read-outs: trajectory, skills, continuity, voids, signals, unclassified |
| `error` | text | |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

`analyzing` and `recommending` are separate states because the Reports screen is shown
before any verdict exists, and because the two model calls fail for different reasons.

### `reports`

Owner: **Engine**. The Analyzer's read of the Profile along one dimension.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `user_id` | uuid | FK → `users`, cascade |
| `run_id` | uuid | FK → `direction_runs`, cascade; unique with `dimension` |
| `dimension` | varchar(16) | `work` · `social` · `learning` · `exercise` · `capacity` · `money` · `unclassified` |
| `period_start` | date | |
| `period_end` | date | |
| `metrics` | jsonb | hours, share, weeks present, longest streak — computed, never narrated |
| `findings` | jsonb | headline, observations, voids, signals — narrated, never computed |
| `created_at` | timestamptz | |

Carrying the run id is what makes the Fit Verdict's citation rule checkable: a re-run writes
new reports without disturbing the ones an existing verdict cited.

### `role_models`

Owner: **Catalog Service**. A borrowed life shape, identical for every user.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `code` | varchar(16) | unique; `S-1`…`S-6` for the shipped six |
| `name` | varchar(128) | |
| `vision` | text | |
| `five_year_path` | text | |
| `must_accumulate` | text | |
| `cost` | text | **NOT NULL** — a template with no stated trade-off is not a Role Model |
| `tags` | text[] | GIN index; controlled by `config/tag_vocab.yaml` |
| `author` | varchar(16) | `system` \| `user` |
| `author_user_id` | uuid | FK → `users`, cascade; set only for user-authored templates |
| `active` | boolean | retired rather than deleted: a hypothesis may still point here |
| `version` | integer | bumped on every upsert by code |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

User-authored templates share this table with the shipped six, so the Recommender scores one
catalogue rather than two. A user sees the system shapes plus their own, never anyone else's.

### `fit_verdicts`

Owner: **Engine**. One Role Model held against one user's evidence.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `user_id` | uuid | FK → `users`, cascade |
| `run_id` | uuid | FK → `direction_runs`, cascade; unique with `role_model_id` |
| `role_model_id` | uuid | FK → `role_models`, cascade |
| `fit` | varchar(24) | `strongly_consistent` … `runs_opposite` |
| `verdict` | text | one line stating the finding |
| `note` | text | what it means, and what it does not mean |
| `evidence` | jsonb | **exactly five** items, each `for`/`against` and each citing a report |
| `probe` | jsonb | the one cheap test, with its own stated cost |
| `created_at` | timestamptz | |

The shape of `evidence` and `probe` is validated in `services/engine/domain/verdict.py`
before the row is written, and a breach is fed back to the model as a retry rather than
stored. Everything computed per user lives here; nothing per-user lives on the Role Model.

The Probe is a value object rather than a table of its own: it is written with the verdict
and never edited, and its outcome is recorded on the Reconciliation.

### `question_answers`

Owner: **API Service**. One of the three constraint questions.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `user_id` | uuid | FK → `users`, cascade |
| `question_key` | varchar(8) | `q1` · `q2` · `q3`; unique with `user_id` |
| `answer` | text | empty when skipped |
| `skipped` | boolean | skipping is an answer, not an omission |
| `answered_at` | timestamptz | |

An answer is personal data, so answering re-queues `profile.build` rather than moving
forward: disagreement is an input to the pipeline, not an exception path around it.

### `quotas`

Owner: **API Service**. What Q-3 declared.

| Column | Type | Notes |
|---|---|---|
| `user_id` | uuid | **PK**, FK → `users`, cascade |
| `drop_first` | varchar(16) | `career` · `relationships` · `health` |
| `weekly_minutes` | integer | the ceiling the Schedule may spend |
| `effective_from` | date | |
| `updated_at` | timestamptz | |

Distinct from capacity, and the two must never be merged. Capacity is observed and says what
is physically possible; the quota is declared and says what has been allowed.

### `direction_hypotheses`

Owner: **API Service**. **Append-only.**

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `user_id` | uuid | FK → `users`, cascade |
| `version` | integer | 0-based; unique with `user_id` |
| `role_model_id` | uuid | FK → `role_models`, **restrict** |
| `fit_verdict_id` | uuid | FK → `fit_verdicts`, **restrict** |
| `source` | varchar(32) | where this version came from |
| `evidence_snapshot` | jsonb | a **copy** of the verdict, not a reference |
| `drop_first` | varchar(16) | the quota at the time, nullable when Q-3 was skipped |
| `answers_count` | integer | how many of the three were answered |
| `review_date` | date | one quarter out |
| `created_at` | timestamptz | |

Three details carry the whole idea. The unique constraint plus the absence of any update
method makes "never overwritten" structural: a hypothesis you could quietly edit could never
be falsified. The `RESTRICT` foreign keys stop a retired shape from taking the record of
what was predicted with it. And the evidence is copied rather than referenced, because a
verdict can be re-run while what this version was built on must stay readable exactly as it
was.

---

## Station 2 · the plan

### `plans`

Owner: **API Service** creates the row with the hypothesis; the **Engine** fills it in.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `user_id` | uuid | FK → `users`, cascade |
| `hypothesis_id` | uuid | FK → `direction_hypotheses`, cascade, **unique** |
| `title` | varchar(128) | empty until generation finishes |
| `status` | varchar(16) | `generating` → `draft` → `active` → `archived`, or `failed` |
| `start_date` | date | nullable; set by the Engine, because where a plan starts is scheduling policy |
| `duration_weeks` | integer | |
| `structure` | jsonb | success criteria, assumptions, the quota, what was trimmed or unplaced, and the baseline schedule |
| `error` | text | |
| `activated_at` | timestamptz | |
| `archived_at` | timestamptz | |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

One plan per hypothesis, and no difficulty variants: the shape has been chosen, and the plan
is what testing it looks like. The row exists from the moment the hypothesis does, so the
client always has something to poll.

`structure.baseline_schedule` is the Schedule as first computed. Station 3 diffs today's
schedule against it, which is the only way "the plan changed" can mean anything later.

### `milestones`

Owner: **Engine**. A checkpoint.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `plan_id` | uuid | FK → `plans`, cascade |
| `parent_id` | uuid | FK → `milestones`, cascade, **nullable** → the tree |
| `key` | varchar(64) | unique with `plan_id`; the identity a milestone keeps between runs |
| `title` | varchar(256) | |
| `metric` | text | how you know it happened |
| `target_date` | date | |
| `depth` | integer | 0-based; at most 3 levels |
| `position` | integer | order among siblings |
| `status` | varchar(16) | |

### `tasks`

Owner: **Engine** creates rows; the **API Service** writes completion.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `plan_id` | uuid | FK → `plans`, cascade |
| `milestone_id` | uuid | FK → `milestones`, cascade, **NOT NULL** |
| `key` | varchar(64) | unique with `plan_id`, `week_index`, `occurrence` |
| `week_index` | integer | 0-based, relative to the plan start |
| `occurrence` | integer | which repetition within the week |
| `area` | varchar(16) | `career` · `relationships` · `health` — what the quota cuts by |
| `task_type` | varchar(16) | `session` · `habit` · `checkpoint` · `rest` |
| `title` | varchar(256) | |
| `description` | text | |
| `duration_minutes` | integer | what it costs against the quota |
| `status` | varchar(16) | `pending` · `done` · `missed` · `skipped` |
| `completed_at` | timestamptz | |
| `sort_order` | integer | |

**A task never contains a task.** `milestone_id` is `NOT NULL` and there is no `parent_id`,
so anything needing further breakdown has to be a sub-milestone. The payoff is that "done"
always means the same thing: the moment tasks nest, completion becomes a weighted-average
argument and every progress number becomes a negotiation.

`(key, week_index, occurrence)` is the alignment key two schedules are diffed on, which is
what lets a task that only moved report as `moved` rather than as a delete plus an add.

### `schedule_slots`

Owner: **Engine** places rows; the **API Service** writes the export columns.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `plan_id` | uuid | FK → `plans`, cascade |
| `task_id` | uuid | FK → `tasks`, cascade, **unique** |
| `start_at` | timestamptz | |
| `end_at` | timestamptz | |
| `all_day` | boolean | checkpoints and rest days |
| `external_ref` | varchar(256) | the calendar event id, kept so a re-push updates rather than duplicates |
| `synced_at` | timestamptz | `NULL` means dirty |

Kept apart from `tasks` on purpose. A Task is relative — what the work is; a Slot is its
projection onto real dates. Separating them means the Schedule can be recomputed without
touching what the plan says, and it makes the determinism line visible in the schema:
everything in this table is arithmetic.

### `checkins`

Owner: **API Service**. What was actually done on one day.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `plan_id` | uuid | FK → `plans`, cascade; unique with `checkin_date` |
| `checkin_date` | date | |
| `task_results` | jsonb | `{task_id, status}[]`, written straight through to `tasks` |
| `note` | text | |
| `created_at` | timestamptz | |

The tasks say what state the work ended in; the check-ins say when the user said so.

### `plan_exports`

Owner: **API Service**.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `plan_id` | uuid | FK → `plans`, cascade; unique with `target` |
| `target` | varchar(32) | `google_calendar` |
| `external_calendar_id` | varchar(256) | the plan's own secondary calendar |
| `last_synced_at` | timestamptz | |
| `status` | varchar(16) | `queued` · `synced` · `failed` |
| `error` | text | `reauth_required` when the Google grant is gone |
| `created_at` | timestamptz | |

---

## Station 3 · reconciliation

### `reconciliations`

Owner: **API Service** creates the row; the **Engine** fills the comparison and the note.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `user_id` | uuid | FK → `users`, cascade |
| `hypothesis_id` | uuid | FK → `direction_hypotheses`, cascade |
| `status` | varchar(16) | `pending` → `done` \| `failed` |
| `period_start` | date | |
| `period_end` | date | |
| `comparison` | jsonb | execution counts, dimension shifts, schedule changes — all computed |
| `narrative` | text | the model's only contribution, written after the numbers |
| `outcome` | varchar(16) | `holds` · `revise` · `replace`; **null until the user answers** |
| `revision_kind` | varchar(16) | `growth` · `avoidance`, classified from the numbers |
| `error` | text | |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |

`outcome` is nullable for a reason: the output of this station is a question, not a score.
The system reads, shows the evidence and hands the decision back. Answering `revise` is what
appends the next version of the hypothesis — the previous one is never touched.

---

## Cross-cutting

### `llm_calls`

Owner: **every service**. Append-only; rows are never updated.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | PK |
| `prompt_name` | varchar(64) | `build_profile` · `create_reports` · `score_role_models` · `build_plan` · `narrate_reconciliation` |
| `prompt_version` | varchar(16) | from the template's frontmatter |
| `provider` | varchar(32) | |
| `model` | varchar(128) | |
| `purpose` | varchar(16) | `analyze` · `verdict` · `generate` |
| `input_tokens` | integer | |
| `output_tokens` | integer | |
| `latency_ms` | integer | |
| `attempts` | integer | how many tries the validation chain needed |
| `degraded` | boolean | true when retries ran out and a fallback was used |
| `job_id` | varchar(64) | |
| `created_at` | timestamptz | |

One row per model call, written by an observer inside the LLM adapter rather than by any use
case. `attempts` and `degraded` together are the cheapest signal that a prompt has started
to rot.
