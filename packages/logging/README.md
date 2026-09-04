# packages/logging

## What it owns

Structured logging for every service: a JSON-lines formatter, the root-logger
setup, and the context variable that carries a `job_id` across a worker's call
stack.

## What it exposes

- `configure_logging(service, level=INFO)` — install the JSON handler and name the service. Idempotent.
- `bind_job_id(job_id)` — context manager attaching `job_id` to every record emitted inside it.
- `current_job_id()` — the currently bound job id, if any.
- `get_logger(name)` — thin `logging.getLogger` wrapper, so callers never import `logging` directly.
- `JsonFormatter` — exported for tests and for anyone wiring their own handler.

Records are one JSON object per line on stdout: `timestamp`, `level`, `logger`,
`event`, `service`, optional `job_id`, plus whatever the caller passed as `extra`.

## What it does not do

No log shipping, no sampling, no rotation — that belongs to the platform. It
does not read configuration; the service decides the level and calls
`configure_logging` from its entry point.
