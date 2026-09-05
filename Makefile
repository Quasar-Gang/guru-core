.PHONY: check test lint type imports fmt integration
check: lint type imports test
# --no-cache because a stale ruff cache has silently passed a file that CI then
# rejected. At this size the cache saves ~10ms and costs a red build.
lint:
	uv run ruff check --no-cache .
	uv run ruff format --check .
fmt:
	uv run ruff format .
	uv run ruff check --no-cache --fix .
type:
	uv run mypy .
imports:
	uv run lint-imports
test:
	uv run pytest
integration:
	uv run pytest -m integration
