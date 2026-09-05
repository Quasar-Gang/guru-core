# Engine

A worker with no HTTP surface. It serves four queues, and between them they are the whole
pipeline past the upload.

| Queue | Produces |
|---|---|
| `profile.build` | the one Profile — classification from a model, coverage from arithmetic |
| `direction.run` | the Reports, then a Fit Verdict for every shape in the catalogue |
| `plan.generate` | the Milestone tree, its Tasks, and the Schedule they land on |
| `reconcile.run` | the quarterly comparison, and the note that puts it into words |

## What it owns

`profiles`, `reports`, `fit_verdicts`, `milestones`, `tasks`, `schedule_slots`, the
transitions on `direction_runs`, and the computed columns of `plans` and `reconciliations`.

## Where the model is allowed to think

Five prompts, three purposes, and a hard line down the middle. The model classifies, judges
and narrates. Everything countable — hours, shares, streaks, placement, the quota's cut
order, the schedule diff, the execution counts — is computed in `domain/`, deterministically.

That is not a preference. A Direction Hypothesis is only falsifiable if the thing it
predicted was computed the same way twice; if the Schedule could drift between two runs of
the same inputs, Station 3 would be comparing against noise.

## Ports it exposes

`ClockPort` only. Everything else it needs is a repo from `packages/repo` or the `LLMPort`
from `packages/llm`.

## What it does not do

No HTTP, no auth, no ownership checks — a job is dispatched by id and the caller already
proved who it was. It never decides an outcome either: `reconciliations.outcome` stays null
until the user answers.
