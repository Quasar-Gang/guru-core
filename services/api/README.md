# API Service

The only front door. Everything the app talks to is here, over HTTP under `/v1`, plus the
worker that parses uploads and pushes the schedule to a calendar.

## What it owns

`users`, `oauth_connections`, `imports`, `documents`, `question_answers`, `quotas`,
`direction_hypotheses`, `plans` (the row and its lifecycle columns), `checkins`,
`plan_exports`, and it creates `direction_runs` and `reconciliations` for the Engine to
fill in.

Two of those carry the weight:

**`direction_hypotheses` is append-only.** There is no update route and no repository method
behind one. A hypothesis you could quietly edit could never be falsified, so `v0` is written
once and left alone; a revision writes `v1`.

**`plans` exists from the moment the hypothesis does**, in status `generating`, so the
client always has something to poll while the Engine works.

## Ports it exposes

`GoogleOidcPort` · `GoogleOAuthPort` · `CalendarPort` · `TokenIssuerPort` ·
`TokenCipherPort` · `ClockPort`, all in `application/ports.py`, each with a real
implementation and a fake under `adapters/`.

## What it does not do

It never calls a model, never schedules anything, and never computes a report. All of that
is the Engine's, reached through the queue. It does not call the Catalog Service over HTTP
either: `role_models` has one writer and the read is the same for every user, so it reads
the table directly.
