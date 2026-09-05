# packages/repo

The ORM schema, one repository protocol per aggregate, and two implementations of each.

## What it owns

`models.py` is the single source of truth for the schema — twenty tables, each naming its
owning service in the first line of its docstring. Alembic autogenerates from it, and
`alembic check` fails the build when the two drift apart.

`entities.py` holds the frozen Pydantic models that cross the boundary. **ORM objects never
leave this package.** Read types mirror the columns one for one; write types (`NewReport`,
`NewMilestone`, `NewTask`, …) carry only what a caller has to supply.

## Ports it exposes

Eighteen protocols in `ports.py`. Most are one table's worth of methods; `PlanTreeRepo` is
the exception, because a Plan's Milestones, Tasks and Schedule Slots are written and replaced
together as one consistent whole, and splitting them would only invite a caller to write half
a tree.

Implementations are grouped by bounded context — `identity`, `intake`, `direction`,
`catalog`, `planning`, `reconciliation` — under `pg/` and `memory/`, so a context's tables
are read and written in one place rather than scattered across a file per table.

## What it does not do

No business rules. A repository stores and retrieves; deciding what may be stored is the
domain's job. The one thing it does enforce is structural: `DirectionHypothesisRepo` has no
update method, because append-only has to be impossible to bypass rather than merely
documented.
