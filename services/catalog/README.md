# Catalog Service

The Role Model catalogue, served over HTTP on 8001. Five use cases, one table, no user data.

## What it owns

`role_models` — and it is the only writer. The six shipped shapes come from
`seeds/role_models/shapes.yaml`; user-authored templates live in the same table with
`author = "user"`, so the Recommender scores one catalogue rather than two.

One rule carries the whole service: **every Role Model states its cost.** `cost` is
`NOT NULL` in the schema and a blank one is rejected in `domain/template.py`. A template
with no stated trade-off turns the catalogue into a popularity contest, won by whichever
sounds best out loud — and that holds for a user's own template exactly as it does for the
shipped six.

## Ports it exposes

None of its own. It uses `RoleModelRepo` from `packages/repo`, and `X-API-Key` guards its
writes.

## What it does not do

It does not score anything. How well a shape fits one person is the Fit Verdict's business,
it is computed from Reports rather than from labels, and it belongs to the Engine. Nothing
per-user is ever stored here.

Retiring a template deactivates it rather than deleting it: a Direction Hypothesis may still
point at it, and the record of what was predicted has to survive.
